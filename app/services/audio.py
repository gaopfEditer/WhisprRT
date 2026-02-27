"""
音频处理服务
"""
import sounddevice as sd
from app.core.logging import logger

class AudioService:
    """音频服务类"""
    
    def __init__(self):
        """初始化音频服务"""
        self.current_device = None
    
    def get_devices(self):
        """
        获取系统上所有可用的音频输入设备
        
        Returns:
            dict: 包含所有可用音频设备的信息
        """
        try:
            devices = sd.query_devices()
            input_devices = []
            
            for i, device in enumerate(devices):
                # 只添加输入设备或双向设备
                if device['max_input_channels'] > 0:
                    input_devices.append({
                        'id': i,
                        'name': device['name'],
                        'channels': device['max_input_channels'],
                        'default': device.get('default_input', False)
                    })
            
            # 找出默认设备
            default_device = None
            try:
                default_device = sd.query_devices(kind='input')
                default_id = default_device['index'] if 'index' in default_device else None
            except:
                default_id = None
                
            return {
                "devices": input_devices,
                "default": default_id
            }
        except Exception as e:
            logger.error(f"获取音频设备失败: {str(e)}")
            return {"status": "error", "message": f"获取音频设备失败: {str(e)}"}
    
    def select_device(self, device_id):
        """
        选择要使用的音频输入设备
        
        Args:
            device_id: 设备ID
        
        Returns:
            dict: 操作状态和消息
        """
        try:
            # 如果设备ID为"default"或空，则使用系统默认设备
            if device_id == "default" or not device_id:
                self.current_device = None
                logger.info("已选择系统默认音频设备")
                return {"status": "success", "message": "已选择系统默认音频设备"}
            
            # 否则尝试使用指定的设备ID
            device_id = int(device_id)
            devices = sd.query_devices()
            
            if device_id >= len(devices) or device_id < 0:
                return {"status": "error", "message": f"无效的设备ID: {device_id}"}
            
            device = devices[device_id]
            if device['max_input_channels'] <= 0:
                return {"status": "error", "message": f"选择的设备不支持音频输入: {device['name']}"}
            
            self.current_device = device_id
            logger.info(f"已选择音频设备: {device['name']} (ID: {device_id})")
            return {"status": "success", "message": f"已选择音频设备: {device['name']}"}
        except Exception as e:
            logger.error(f"选择音频设备失败: {str(e)}")
            return {"status": "error", "message": f"选择音频设备失败: {str(e)}"}
    
    def _get_all_input_device_ids(self):
        """获取所有支持输入的设备 ID 列表"""
        try:
            devices = sd.query_devices()
            return [i for i, d in enumerate(devices) if d['max_input_channels'] > 0]
        except Exception as e:
            logger.warning(f"枚举音频设备失败: {e}")
        return []

    def _create_stream_with_device(self, device_id, samplerate, channels, dtype, callback, blocksize):
        """使用指定设备创建输入流，可传入 device_id 或 None（使用默认）"""
        kwargs = dict(
            samplerate=samplerate,
            channels=channels,
            dtype=dtype,
            callback=callback,
            blocksize=blocksize,
            latency="high",  # Windows 上提高延迟可提高兼容性
        )
        if device_id is not None:
            kwargs["device"] = device_id
        return sd.InputStream(**kwargs)

    def create_input_stream(self, samplerate, channels, dtype, callback, blocksize):
        """
        创建音频输入流
        
        Args:
            samplerate: 采样率
            channels: 通道数
            dtype: 数据类型
            callback: 回调函数
            blocksize: 块大小
            
        Returns:
            InputStream: 音频输入流
        """
        try:
            device_id = self.current_device

            def try_open(dev_id, label):
                try:
                    logger.info(f"尝试打开音频流: {label}")
                    return self._create_stream_with_device(
                        dev_id, samplerate, channels, dtype, callback, blocksize
                    )
                except sd.PortAudioError as e:
                    logger.warning(f"设备 {label} 打开失败: {e}")
                    return None

            if device_id is None:
                # 1. 先尝试系统默认设备
                stream = try_open(None, "系统默认")
                if stream is not None:
                    return stream

                # 2. 默认不可用，逐个尝试所有输入设备
                device_ids = self._get_all_input_device_ids()
                if not device_ids:
                    raise RuntimeError(
                        "未找到可用的麦克风设备，请检查是否已连接麦克风并在 Windows 设置中启用"
                    )
                devices = sd.query_devices()
                for did in device_ids:
                    name = devices[did]["name"] if did < len(devices) else str(did)
                    stream = try_open(did, f"{name} (ID:{did})")
                    if stream is not None:
                        return stream

                raise RuntimeError(
                    "所有麦克风设备均无法打开，请检查 Windows 声音设置和麦克风权限"
                )

            # 使用用户指定的设备
            devices = sd.query_devices()
            if device_id >= len(devices) or device_id < 0:
                logger.error(f"无效的设备ID: {device_id}，尝试其他设备")
                for did in self._get_all_input_device_ids():
                    stream = try_open(did, f"ID:{did}")
                    if stream is not None:
                        return stream
                raise RuntimeError("无法打开任何音频输入设备")

            stream = try_open(device_id, devices[device_id]["name"])
            if stream is not None:
                return stream
            # 指定设备失败，尝试其他设备
            for did in self._get_all_input_device_ids():
                if did == device_id:
                    continue
                stream = try_open(did, f"ID:{did}")
                if stream is not None:
                    return stream
            raise RuntimeError("无法打开任何音频输入设备，请检查麦克风设置")
        except sd.PortAudioError:
            raise
        except Exception as e:
            logger.error(f"创建音频输入流失败: {str(e)}")
            raise

# 创建全局音频服务实例
audio_service = AudioService()