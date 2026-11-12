from django.http import HttpResponse
from django.shortcuts import render
from rest_framework import permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from .models import AssistantSession, ChatMessage, DifyConfig
from .ragflow_client import (
    RagflowError,
    chat_completion,
    fetch_chunk_image,
    is_session_error,
    normalize_reference,
)
from .serializers import (
    AssistantMessageSerializer,
    AssistantSessionCreateSerializer,
    AssistantSessionSerializer,
    ChatMessageSerializer,
)


class AssistantSessionViewSet(viewsets.ModelViewSet):
    """智能助手会话视图集"""
    permission_classes = [permissions.IsAuthenticated]

    def get_serializer_class(self):
        if self.action in ['create', 'update', 'partial_update']:
            return AssistantSessionCreateSerializer
        return AssistantSessionSerializer

    def get_queryset(self):
        return AssistantSession.objects.filter(user=self.request.user)

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)

    def create(self, request, *args, **kwargs):
        """创建后返回完整会话，前端需要主键才能切换和删除。"""
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        output = AssistantSessionSerializer(serializer.instance)
        headers = self.get_success_headers(output.data)
        return Response(output.data, status=status.HTTP_201_CREATED, headers=headers)

    @action(detail=True, methods=['post'])
    def add_message(self, request, pk=None):
        """添加消息到会话"""
        session = self.get_object()
        serializer = AssistantMessageSerializer(data=request.data)

        if serializer.is_valid():
            serializer.save(session=session)
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['get'])
    def messages(self, request, pk=None):
        """获取会话的聊天消息"""
        session = self.get_object()
        messages = session.chat_messages.all()
        serializer = ChatMessageSerializer(messages, many=True)
        return Response(serializer.data)


class ChatViewSet(viewsets.ViewSet):
    """聊天功能ViewSet"""
    permission_classes = [permissions.IsAuthenticated]

    @action(detail=False, methods=['post'])
    def send_message(self, request):
        """发送消息到 RAGFlow"""
        session_id = request.data.get('session_id')
        message = request.data.get('message')

        if not session_id or not message:
            return Response(
                {'error': 'session_id和message都是必填项'},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            session = AssistantSession.objects.get(
                session_id=session_id,
                user=request.user
            )
        except AssistantSession.DoesNotExist:
            return Response(
                {'error': '会话不存在'},
                status=status.HTTP_404_NOT_FOUND
            )

        ragflow_config = DifyConfig.get_active_config()
        if not ragflow_config:
            return Response(
                {'error': '未配置 RAGFlow API，请先在配置中心配置'},
                status=status.HTTP_400_BAD_REQUEST
            )
        if not ragflow_config.chat_id:
            return Response(
                {'error': '未配置 RAGFlow Chat ID，请先在配置中心填写 Chat Assistant ID'},
                status=status.HTTP_400_BAD_REQUEST
            )

        user_message = ChatMessage.objects.create(
            session=session,
            role='user',
            content=message,
            conversation_id=session.conversation_id
        )

        try:
            data = chat_completion(
                api_url=ragflow_config.api_url,
                api_key=ragflow_config.api_key,
                question=message,
                chat_id=ragflow_config.chat_id,
                session_id=session.conversation_id,
            )
        except RagflowError as exc:
            if session.conversation_id and is_session_error(exc):
                try:
                    data = chat_completion(
                        api_url=ragflow_config.api_url,
                        api_key=ragflow_config.api_key,
                        question=message,
                        chat_id=ragflow_config.chat_id,
                        session_id=None,
                    )
                except RagflowError as retry_exc:
                    return _ragflow_error_response(retry_exc)
            else:
                return _ragflow_error_response(exc)

        ragflow_session_id = data.get('session_id') or session.conversation_id
        if ragflow_session_id and ragflow_session_id != session.conversation_id:
            session.conversation_id = ragflow_session_id
            session.save(update_fields=['conversation_id', 'updated_at'])

        assistant_message = ChatMessage.objects.create(
            session=session,
            role='assistant',
            content=data.get('answer', ''),
            conversation_id=ragflow_session_id,
            message_id=data.get('id') or data.get('message_id'),
            references=normalize_reference(data.get('reference')),
        )

        return Response({
            'user_message': ChatMessageSerializer(user_message).data,
            'assistant_message': ChatMessageSerializer(assistant_message).data,
            'conversation_id': ragflow_session_id,
        })

    @action(detail=False, methods=['get'], url_path='reference_image')
    def reference_image(self, request):
        """Proxy a RAGFlow page snapshot so the browser does not need the API key."""
        config = DifyConfig.get_active_config()
        if not config:
            return Response(
                {'error': '未配置 RAGFlow API，请先在配置中心配置'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            content, media_type = fetch_chunk_image(
                api_url=config.api_url,
                api_key=config.api_key,
                image_id=request.query_params.get('image_id') or '',
            )
        except RagflowError:
            return Response({'error': '原文图片不可用'}, status=status.HTTP_404_NOT_FOUND)
        response = HttpResponse(content, content_type=media_type)
        response['Cache-Control'] = 'private, max-age=3600'
        return response


def _ragflow_error_response(exc):
    payload = {'error': exc.message}
    if exc.detail is not None:
        payload['detail'] = exc.detail
    status_code = exc.status_code or 500
    if status_code == 408:
        http_status = status.HTTP_408_REQUEST_TIMEOUT
    elif status_code >= 500:
        http_status = status.HTTP_500_INTERNAL_SERVER_ERROR
    else:
        http_status = status.HTTP_400_BAD_REQUEST
    return Response(payload, status=http_status)


def assistant_view(request):
    """智能助手页面视图 - 用于iframe内嵌"""
    return render(request, 'assistant/assistant.html')
