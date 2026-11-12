from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from .models import DifyConfig
from .serializers import DifyConfigSerializer
from .ragflow_client import RagflowError, list_chats


class DifyConfigViewSet(viewsets.ModelViewSet):
    """RAGFlow 配置管理 ViewSet（路由仍使用 /assistant/config/dify/，避免前端大改）"""
    queryset = DifyConfig.objects.all()
    serializer_class = DifyConfigSerializer
    permission_classes = [IsAuthenticated]

    def list(self, request):
        """获取激活的配置"""
        active_config = DifyConfig.get_active_config()
        if active_config:
            data = self.get_serializer(active_config).data
            if active_config.api_key:
                data['api_key_masked'] = active_config.api_key[:8] + '****'
            return Response(data)
        return Response({'message': '未找到激活的配置'}, status=status.HTTP_404_NOT_FOUND)

    def create(self, request):
        """创建新配置"""
        if request.data.get('is_active', True):
            DifyConfig.objects.update(is_active=False)

        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    def update(self, request, pk=None, partial=False):
        """更新配置"""
        instance = self.get_object()

        if request.data.get('is_active', False):
            DifyConfig.objects.exclude(pk=pk).update(is_active=False)

        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)

    def partial_update(self, request, pk=None):
        """部分更新配置"""
        return self.update(request, pk=pk, partial=True)

    @action(detail=False, methods=['post'])
    def test_connection(self, request):
        """测试 RAGFlow API 连接，并可校验 Chat ID"""
        api_url = request.data.get('api_url')
        api_key = request.data.get('api_key')
        chat_id = (request.data.get('chat_id') or '').strip()

        if not api_key:
            active = DifyConfig.get_active_config()
            if active:
                api_key = active.api_key
                api_url = api_url or active.api_url
                if not chat_id:
                    chat_id = active.chat_id or ''

        if not api_url or not api_key:
            return Response(
                {'error': 'API URL 和 API Key 都是必填项', 'success': False},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            chats = list_chats(api_url, api_key, chat_id=chat_id or None)
            summaries = [
                {'id': item.get('id'), 'name': item.get('name')}
                for item in chats
                if isinstance(item, dict)
            ]
            if chat_id and not summaries:
                return Response(
                    {
                        'error': f'已连接到 RAGFlow，但找不到 Chat ID: {chat_id}',
                        'success': False,
                        'chats': summaries,
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )
            return Response({
                'message': '连接成功！',
                'success': True,
                'chats': summaries,
            })
        except RagflowError as exc:
            http_status = status.HTTP_408_REQUEST_TIMEOUT if exc.status_code == 408 else status.HTTP_400_BAD_REQUEST
            return Response(
                {'error': exc.message, 'detail': exc.detail, 'success': False},
                status=http_status,
            )
