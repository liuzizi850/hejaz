package com.testhub.recorder;

import android.accessibilityservice.AccessibilityService;
import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.content.IntentFilter;
import android.graphics.Rect;
import android.os.Build;
import android.os.Handler;
import android.os.Looper;
import android.util.DisplayMetrics;
import android.util.Log;
import android.view.ViewConfiguration;
import android.view.WindowManager;
import android.view.accessibility.AccessibilityEvent;
import android.view.accessibility.AccessibilityNodeInfo;

import org.json.JSONException;
import org.json.JSONObject;

import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

/**
 * Posts accessibility events after {@code com.testhub.recorder.START}.
 * {@code com.testhub.recorder.STOP} stops further posts.
 */
public class RecorderService extends AccessibilityService {
    static final String ACTION_START = "com.testhub.recorder.START";
    static final String ACTION_STOP = "com.testhub.recorder.STOP";
    static final String EXTRA_INGEST_URL = "ingestUrl";

    private static final String TAG = "RecorderService";

    private final ExecutorService poster = Executors.newSingleThreadExecutor(runnable -> {
        Thread thread = new Thread(runnable, "testhub-recorder-post");
        thread.setDaemon(true);
        return thread;
    });

    private static final long FIELD_WATCH_MS = 300;

    private volatile boolean posting;
    private volatile String ingestUrl = "";
    private volatile String lastSentText = "";
    private BroadcastReceiver controlReceiver;
    private boolean receiverRegistered;
    private Handler handler;
    private final Runnable watchField = new Runnable() {
        @Override
        public void run() {
            if (!posting) {
                return;
            }
            sampleFocusedText();
            if (handler != null) {
                handler.postDelayed(this, FIELD_WATCH_MS);
            }
        }
    };

    @Override
    public void onCreate() {
        super.onCreate();
        handler = new Handler(Looper.getMainLooper());
        registerControlReceiver();
    }

    @Override
    public void onAccessibilityEvent(AccessibilityEvent event) {
        if (!posting || ingestUrl == null || ingestUrl.isEmpty() || event == null) {
            return;
        }
        sampleFocusedText();
        String eventType = eventTypeOf(event.getEventType());
        if (eventType == null) {
            return;
        }
        if ("input".equals(eventType) && !rememberInputText(event)) {
            return;
        }
        final String url = ingestUrl;
        try {
            final String payload = buildPayload(event, eventType);
            poster.execute(() -> {
                if (!posting) {
                    return;
                }
                postJson(url, payload);
            });
        } catch (Exception error) {
            Log.w(TAG, "record failed: " + eventType, error);
        }
    }

    @Override
    public void onInterrupt() {
    }

    @Override
    public void onDestroy() {
        posting = false;
        ingestUrl = "";
        stopWatching();
        if (receiverRegistered && controlReceiver != null) {
            try {
                unregisterReceiver(controlReceiver);
            } catch (RuntimeException error) {
                Log.w(TAG, "unregister control receiver failed", error);
            }
            receiverRegistered = false;
        }
        poster.shutdownNow();
        super.onDestroy();
    }

    private void registerControlReceiver() {
        if (receiverRegistered) {
            return;
        }
        controlReceiver = new BroadcastReceiver() {
            @Override
            public void onReceive(Context context, Intent intent) {
                handleControl(intent);
            }
        };
        IntentFilter filter = new IntentFilter();
        filter.addAction(ACTION_START);
        filter.addAction(ACTION_STOP);
        try {
            if (Build.VERSION.SDK_INT >= 33) {
                registerReceiver(controlReceiver, filter, Context.RECEIVER_EXPORTED);
            } else {
                registerReceiver(controlReceiver, filter);
            }
            receiverRegistered = true;
        } catch (RuntimeException error) {
            Log.e(TAG, "register control receiver failed", error);
        }
    }

    private void handleControl(Intent intent) {
        if (intent == null || intent.getAction() == null) {
            return;
        }
        if (ACTION_START.equals(intent.getAction())) {
            String url = intent.getStringExtra(EXTRA_INGEST_URL);
            if (url == null || url.trim().isEmpty()) {
                Log.w(TAG, "START missing ingestUrl");
                return;
            }
            ingestUrl = url.trim();
            posting = true;
            lastSentText = "";
            startWatching();
            Log.i(TAG, "recording started");
        } else if (ACTION_STOP.equals(intent.getAction())) {
            posting = false;
            ingestUrl = "";
            stopWatching();
            Log.i(TAG, "recording stopped");
        }
    }

    private String buildPayload(AccessibilityEvent event, String eventType) throws JSONException {
        AccessibilityNodeInfo node = null;
        try {
            node = event.getSource();
            boolean password = "input".equals(eventType) && node != null && node.isPassword();
            String nodeText = node == null ? "" : asString(node.getText());
            String text = visibleText(event, eventType, password, nodeText);

            JSONObject bounds = new JSONObject();
            Rect rect = new Rect();
            if (node != null) {
                node.getBoundsInScreen(rect);
            }
            int[] screen = readScreenSize();
            bounds.put("x", fraction(rect.left, screen[0]));
            bounds.put("y", fraction(rect.top, screen[1]));
            bounds.put("w", fraction(rect.width(), screen[0]));
            bounds.put("h", fraction(rect.height(), screen[1]));

            JSONObject screenJson = new JSONObject();
            screenJson.put("width", screen[0]);
            screenJson.put("height", screen[1]);

            JSONObject body = new JSONObject();
            body.put("event_type", eventType);
            body.put("resource_id", node == null ? "" : asString(node.getViewIdResourceName()));
            body.put("content_desc", node == null ? "" : asString(node.getContentDescription()));
            body.put("text", text);
            body.put("class_name", node == null ? "" : asString(node.getClassName()));
            body.put("bounds", bounds);
            body.put("screen", screenJson);
            if ("click".equals(eventType)) {
                body.put("duration_ms", 0);
            } else if ("long_press".equals(eventType)) {
                body.put("duration_ms", ViewConfiguration.getLongPressTimeout());
            } else if ("swipe".equals(eventType)) {
                putSwipe(body, event);
            } else if ("input".equals(eventType)) {
                body.put("password", password);
                body.put("input_text", password ? "" : text);
            }
            return body.toString();
        } finally {
            if (node != null) {
                node.recycle();
            }
        }
    }

    private static String visibleText(AccessibilityEvent event, String eventType, boolean password, String nodeText) {
        if ("input".equals(eventType) && password) {
            return "";
        }
        if ("input".equals(eventType)) {
            String changed = eventText(event);
            if (changed.length() >= nodeText.length() && !changed.isEmpty()) {
                return changed;
            }
            return nodeText.isEmpty() ? changed : nodeText;
        }
        return nodeText.isEmpty() ? eventText(event) : nodeText;
    }

    private static void putSwipe(JSONObject body, AccessibilityEvent event) throws JSONException {
        int fromIndex = event.getFromIndex();
        int toIndex = event.getToIndex();
        int itemCount = event.getItemCount();
        double distance = 0;
        if (itemCount > 0) {
            distance = Math.abs(fromIndex - toIndex) / (double) itemCount;
        }
        if (distance < 0) {
            distance = 0;
        } else if (distance > 1) {
            distance = 1;
        }
        body.put("direction", fromIndex > toIndex ? "up" : "down");
        body.put("distance", distance);
    }

    private static String eventTypeOf(int type) {
        switch (type) {
            case AccessibilityEvent.TYPE_VIEW_CLICKED:
                return "click";
            case AccessibilityEvent.TYPE_VIEW_LONG_CLICKED:
                return "long_press";
            case AccessibilityEvent.TYPE_VIEW_SCROLLED:
                return "swipe";
            case AccessibilityEvent.TYPE_VIEW_TEXT_CHANGED:
                return "input";
            default:
                return null;
        }
    }

    @SuppressWarnings("deprecation")
    private int[] readScreenSize() {
        try {
            WindowManager manager = (WindowManager) getSystemService(WINDOW_SERVICE);
            if (manager != null) {
                DisplayMetrics metrics = new DisplayMetrics();
                manager.getDefaultDisplay().getRealMetrics(metrics);
                if (metrics.widthPixels > 0 && metrics.heightPixels > 0) {
                    return new int[]{metrics.widthPixels, metrics.heightPixels};
                }
            }
        } catch (RuntimeException error) {
            Log.w(TAG, "screen size unavailable", error);
        }
        DisplayMetrics fallback = getResources().getDisplayMetrics();
        return new int[]{fallback.widthPixels, fallback.heightPixels};
    }

    private static double fraction(int value, int total) {
        if (total <= 0) {
            return 0;
        }
        double result = (double) value / (double) total;
        if (result < 0) {
            return 0;
        }
        if (result > 1) {
            return 1;
        }
        return result;
    }

    private static String asString(CharSequence value) {
        return value == null ? "" : value.toString();
    }

    private static String eventText(AccessibilityEvent event) {
        if (event.getText() == null || event.getText().isEmpty()) {
            return "";
        }
        StringBuilder builder = new StringBuilder();
        for (CharSequence part : event.getText()) {
            if (part != null) {
                builder.append(part);
            }
        }
        return builder.toString();
    }

    private void startWatching() {
        if (handler == null) {
            return;
        }
        handler.removeCallbacks(watchField);
        handler.post(watchField);
    }

    private void stopWatching() {
        if (handler != null) {
            handler.removeCallbacks(watchField);
        }
        lastSentText = "";
    }

    private boolean rememberInputText(AccessibilityEvent event) {
        AccessibilityNodeInfo source = event.getSource();
        try {
            boolean password = source != null && source.isPassword();
            String nodeText = source == null ? "" : asString(source.getText());
            String text = visibleText(event, "input", password, nodeText);
            if (password) {
                return true;
            }
            if (text.isEmpty() || text.equals(lastSentText)) {
                return false;
            }
            lastSentText = text;
            return true;
        } finally {
            if (source != null) {
                source.recycle();
            }
        }
    }

    private void sampleFocusedText() {
        if (!posting || ingestUrl == null || ingestUrl.isEmpty()) {
            return;
        }
        AccessibilityNodeInfo focused = null;
        try {
            focused = findFocus(AccessibilityNodeInfo.FOCUS_INPUT);
            if (focused == null || focused.isPassword()) {
                return;
            }
            String text = asString(focused.getText());
            if (text.isEmpty()) {
                lastSentText = "";
                return;
            }
            if (text.equals(lastSentText)) {
                return;
            }
            lastSentText = text;
            final String payload = buildInputPayload(focused, text);
            final String url = ingestUrl;
            Log.i(TAG, "field text posted, length=" + text.length());
            poster.execute(() -> {
                if (!posting) {
                    return;
                }
                postJson(url, payload);
            });
        } catch (Exception error) {
            Log.w(TAG, "sample field failed", error);
        } finally {
            if (focused != null) {
                focused.recycle();
            }
        }
    }

    private String buildInputPayload(AccessibilityNodeInfo node, String text) throws JSONException {
        JSONObject bounds = new JSONObject();
        Rect rect = new Rect();
        node.getBoundsInScreen(rect);
        int[] screen = readScreenSize();
        bounds.put("x", fraction(rect.left, screen[0]));
        bounds.put("y", fraction(rect.top, screen[1]));
        bounds.put("w", fraction(rect.width(), screen[0]));
        bounds.put("h", fraction(rect.height(), screen[1]));
        JSONObject screenJson = new JSONObject();
        screenJson.put("width", screen[0]);
        screenJson.put("height", screen[1]);
        JSONObject body = new JSONObject();
        body.put("event_type", "input");
        body.put("resource_id", asString(node.getViewIdResourceName()));
        body.put("content_desc", asString(node.getContentDescription()));
        body.put("text", text);
        body.put("class_name", asString(node.getClassName()));
        body.put("bounds", bounds);
        body.put("screen", screenJson);
        body.put("password", false);
        body.put("input_text", text);
        return body.toString();
    }

    private void postJson(String url, String json) {
        HttpURLConnection connection = null;
        try {
            connection = (HttpURLConnection) new URL(url).openConnection();
            connection.setConnectTimeout(4000);
            connection.setReadTimeout(4000);
            connection.setDoOutput(true);
            connection.setRequestMethod("POST");
            connection.setRequestProperty("Content-Type", "application/json; charset=utf-8");
            byte[] bytes = json.getBytes(StandardCharsets.UTF_8);
            connection.setFixedLengthStreamingMode(bytes.length);
            try (OutputStream output = connection.getOutputStream()) {
                output.write(bytes);
            }
            int code = connection.getResponseCode();
            discard(code >= 200 && code < 300 ? connection.getInputStream() : connection.getErrorStream());
            if (code < 200 || code >= 300) {
                Log.w(TAG, "ingest http " + code);
            }
        } catch (Exception error) {
            Log.w(TAG, "ingest failed", error);
        } finally {
            if (connection != null) {
                connection.disconnect();
            }
        }
    }

    private static void discard(InputStream stream) {
        if (stream == null) {
            return;
        }
        try (InputStream input = stream) {
            byte[] buffer = new byte[256];
            while (input.read(buffer) != -1) {
                // Response body is not needed.
            }
        } catch (Exception error) {
            Log.w(TAG, "discard response failed", error);
        }
    }
}
