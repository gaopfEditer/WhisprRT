"""
Whisper 模型服务
"""
import os
from pathlib import Path
from faster_whisper import WhisperModel
from app.core.logging import logger
from app.config import DEFAULT_MODEL, ANTI_HALLUCINATION_CONFIG

class WhisperService:
    """Whisper 模型服务类"""
    
    def __init__(self):
        """初始化 Whisper 服务（延迟加载模型）"""
        self.model = None
        self.model_name = DEFAULT_MODEL
        self._model_loaded = False
        # 不在初始化时加载模型，延迟到第一次使用时加载
        logger.info(f"WhisperService 初始化完成，模型将在首次使用时加载: {DEFAULT_MODEL}")
    
    def _get_local_model_path(self, model_name):
        """
        获取模型的本地缓存路径
        
        Args:
            model_name: 模型名称
            
        Returns:
            str: 本地路径，如果不存在则返回 None
        """
        try:
            # Hugging Face 缓存路径
            cache_dir = Path(os.path.expanduser("~/.cache/huggingface/hub"))
            
            # 将模型名称转换为缓存目录名
            # 例如: "tiny" -> "models--Systran--faster-whisper-tiny"
            if model_name.startswith("Systran/"):
                repo_id = model_name
            else:
                repo_id = f"Systran/faster-whisper-{model_name}"
            
            # 查找缓存目录
            model_cache_dir = cache_dir / f"models--{repo_id.replace('/', '--')}"
            if model_cache_dir.exists():
                # 查找 snapshots 目录
                snapshots_dir = model_cache_dir / "snapshots"
                if snapshots_dir.exists():
                    # 获取最新的 snapshot
                    snapshots = list(snapshots_dir.iterdir())
                    if snapshots:
                        latest_snapshot = max(snapshots, key=lambda p: p.stat().st_mtime)
                        return str(latest_snapshot)
        except Exception as e:
            logger.debug(f"无法获取本地模型路径: {str(e)}")
        
        return None
    
    def _ensure_model_loaded(self):
        """确保模型已加载，如果未加载则加载"""
        if self.model is None or not self._model_loaded:
            self.load_model(self.model_name)
    
    def load_model(self, model_name):
        """
        加载指定的 Whisper 模型
        
        Args:
            model_name: 模型名称或本地路径
            
        Returns:
            WhisperModel: 加载的模型实例
        """
        try:
            logger.info(f"正在加载模型: {model_name}")
            
            # 配置 Hugging Face 镜像和 Token（如果设置了环境变量）
            hf_mirror = os.getenv("HF_ENDPOINT", "")
            hf_token = os.getenv("HF_TOKEN", "")
            
            if hf_mirror:
                logger.info(f"使用 Hugging Face 镜像: {hf_mirror}")
            if hf_token:
                logger.info("检测到 Hugging Face Token，将使用认证下载")
            
            # 如果遇到 429 错误，建议使用 token
            # token 通过环境变量自动传递给 huggingface_hub，不需要传递给 WhisperModel
            # 注意：如果模型已下载到本地，使用本地路径可以避免 token 传递问题
            try:
                # 尝试使用本地路径（如果模型已下载）
                local_model_path = self._get_local_model_path(model_name)
                model_path = local_model_path if local_model_path and os.path.exists(local_model_path) else model_name
                
                self.model = WhisperModel(
                    model_path, 
                    device="cpu",           
                    compute_type="int8",   
                    cpu_threads=8,  # 使用 cpu_threads（faster-whisper 的正确参数名）
                    num_workers=1  # 使用 num_workers（faster-whisper 的正确参数名）
                )
                self.model_name = model_name
                self._model_loaded = True
                logger.info(f"模型 {model_name} 加载成功")
                return self.model
            except Exception as e:
                error_msg = str(e)
                
                # 检查是否是 429 限流错误
                if "429" in error_msg or "Too Many Requests" in error_msg or "rate limit" in error_msg.lower():
                    logger.error("=" * 70)
                    logger.error("⚠️  遇到 429 限流错误！镜像站点限制了您的 IP 访问频率。")
                    logger.error("")
                    logger.error("解决方案（按优先级）：")
                    logger.error("")
                    logger.error("方案 1：使用 Hugging Face Token（推荐）")
                    logger.error("   1. 访问 https://huggingface.co/settings/tokens 创建 token")
                    logger.error("   2. 设置环境变量：")
                    logger.error("      PowerShell: $env:HF_TOKEN='your_token_here'")
                    logger.error("      CMD: set HF_TOKEN=your_token_here")
                    logger.error("")
                    logger.error("方案 2：等待一段时间后重试（限流会在一段时间后解除）")
                    logger.error("")
                    logger.error("方案 3：使用代理或 VPN 更换 IP")
                    logger.error("")
                    logger.error("方案 4：手动下载模型到本地（详见 MODEL_DOWNLOAD_GUIDE.md）")
                    logger.error("=" * 70)
                    raise
                
                # 检查是否是网络连接问题
                if "internet connection" in error_msg.lower() or "timeout" in error_msg.lower() or "connection" in error_msg.lower():
                    logger.error("=" * 70)
                    logger.error("网络连接失败！无法从 Hugging Face 下载模型。")
                    logger.error("解决方案：")
                    logger.error("1. 设置 Hugging Face 镜像：")
                    logger.error("   PowerShell: $env:HF_ENDPOINT='https://hf-mirror.com'")
                    logger.error("   CMD: set HF_ENDPOINT=https://hf-mirror.com")
                    logger.error("2. 或使用代理")
                    logger.error("3. 或先使用较小的模型测试（tiny/base/small）")
                    logger.error("=" * 70)
                    raise
                
                # 其他错误直接抛出
                raise
                
        except Exception as e:
            error_msg = str(e)
            logger.error(f"模型加载失败: {error_msg}")
            
            # 如果加载失败，尝试加载默认模型（仅当不是默认模型时）
            if model_name != DEFAULT_MODEL:
                logger.info(f"尝试加载默认模型: {DEFAULT_MODEL}")
                try:
                    # 尝试使用本地路径
                    local_model_path = self._get_local_model_path(DEFAULT_MODEL)
                    model_path = local_model_path if local_model_path and os.path.exists(local_model_path) else DEFAULT_MODEL
                    
                    self.model = WhisperModel(
                        model_path, 
                        device="cpu", 
                        compute_type="int8", 
                        cpu_threads=8,  # 使用 cpu_threads（faster-whisper 的正确参数名）
                        num_workers=1  # 使用 num_workers（faster-whisper 的正确参数名）
                    )
                    self.model_name = DEFAULT_MODEL
                    self._model_loaded = True
                    logger.info(f"默认模型 {DEFAULT_MODEL} 加载成功")
                    return self.model
                except Exception as e2:
                    logger.error(f"默认模型也加载失败: {str(e2)}")
            
            raise
    
    def transcribe(self, audio_samples, language):
        """
        转写音频
        
        Args:
            audio_samples: 音频样本数据
            language: 语言代码
            
        Returns:
            tuple: (segments, info) 转写结果和信息
        """
        # 确保模型已加载
        self._ensure_model_loaded()
        
        # 使用速度优化的推理参数
        config = ANTI_HALLUCINATION_CONFIG
        return self.model.transcribe(
            audio_samples, 
            language=language,
            beam_size=1,                          # 从默认5降到1，大幅提升速度
            best_of=1,                           # 从默认5降到1，提升速度
            temperature=config["temperature"],
            no_speech_threshold=config["no_speech_threshold"],
            condition_on_previous_text=config["condition_on_previous_text"],
            compression_ratio_threshold=config["compression_ratio_threshold"],
            log_prob_threshold=config["log_prob_threshold"],
            initial_prompt=config["initial_prompt"],
            word_timestamps=False,                # 不生成词级时间戳，提升速度
            vad_filter=True,                     # 启用 VAD 过滤，减少无效推理
            vad_parameters=dict(
                min_silence_duration_ms=500,      # 最小静音持续时间
                speech_pad_ms=400                 # 语音填充时间
            )
        )

# 创建全局 Whisper 服务实例
whisper_service = WhisperService()