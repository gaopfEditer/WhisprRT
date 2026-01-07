# 模型下载问题解决方案

## 问题描述

### 错误 1：网络连接失败
```
模型加载失败: An error happened while trying to locate the files on the Hub 
and we cannot find the appropriate snapshot folder for the specified revision 
on the local disk. Please check your internet connection and try again.
```
这通常是因为无法连接到 Hugging Face 下载模型。

### 错误 2：429 限流错误（常见）
```
429 Client Error: Too Many Requests
We had to rate limit your IP. To continue using our service, create a HF account 
or login to your existing account, and make sure you pass a HF_TOKEN if you're using the API.
```
这是因为镜像站点对您的 IP 进行了限流，需要等待或使用 Token。

## 解决方案

### ⚠️ 重要更新：延迟加载模型

**现在模型不会在启动时立即加载**，而是在首次使用时才加载。这意味着：
- ✅ 项目可以正常启动，即使模型还未下载
- ✅ 模型会在您第一次点击"开始转写"时自动下载
- ✅ 如果下载失败，会有更友好的错误提示

### 方案 1：使用 Hugging Face Token（推荐，解决 429 错误）

如果遇到 429 限流错误，使用 Token 是最有效的解决方案：

#### 步骤：
1. **创建 Token**：
   - 访问 https://huggingface.co/settings/tokens
   - 点击 "New token"
   - 选择 "Read" 权限（读取权限即可）
   - 复制生成的 token

2. **设置 Token**：

   **Windows PowerShell:**
   ```powershell
   $env:HF_TOKEN = "your_token_here"
   # 或运行脚本
   .\setup_hf_token.ps1
   ```

   **Windows CMD:**
   ```cmd
   set HF_TOKEN=your_token_here
   ```

   **Linux/MacOS:**
   ```bash
   export HF_TOKEN=your_token_here
   ```

3. **永久设置**（推荐）：
   - 右键"此电脑" → "属性" → "高级系统设置"
   - 点击"环境变量"
   - 新建用户变量：
     - 变量名：`HF_TOKEN`
     - 变量值：您的 token

4. **重新启动项目**

### 方案 2：使用 Hugging Face 镜像（适合中国用户）

#### Windows PowerShell:
```powershell
# 临时设置（仅当前会话有效）
$env:HF_ENDPOINT = "https://hf-mirror.com"

# 或运行提供的脚本
.\setup_hf_mirror.ps1
```

#### Windows CMD:
```cmd
# 临时设置（仅当前会话有效）
set HF_ENDPOINT=https://hf-mirror.com

# 或运行提供的脚本
setup_hf_mirror.bat
```

#### Linux/MacOS:
```bash
export HF_ENDPOINT=https://hf-mirror.com
```

#### 永久设置（推荐）：
1. 右键"此电脑" -> "属性" -> "高级系统设置"
2. 点击"环境变量"
3. 在"用户变量"中点击"新建"
4. 变量名：`HF_ENDPOINT`
5. 变量值：`https://hf-mirror.com`
6. 点击"确定"保存

### 方案 3：等待限流解除

如果遇到 429 错误且暂时无法使用 Token：
- 等待 10-30 分钟后重试
- 限流通常会在一定时间后自动解除

### 方案 4：使用代理

如果您有代理服务器：

#### Windows PowerShell:
```powershell
$env:HTTP_PROXY = "http://your-proxy:port"
$env:HTTPS_PROXY = "http://your-proxy:port"
```

#### Windows CMD:
```cmd
set HTTP_PROXY=http://your-proxy:port
set HTTPS_PROXY=http://your-proxy:port
```

### 方案 5：先使用较小的模型测试

如果网络问题暂时无法解决，可以先使用较小的模型：

1. 编辑 `app/config.py`，将 `DEFAULT_MODEL` 改为：
   ```python
   DEFAULT_MODEL = "tiny"  # 或 "base" 或 "small"
   ```

2. 较小的模型更容易下载，可以先用它们测试功能

3. 网络正常后，再改回 `"large-v3-turbo"`

### 方案 6：手动下载模型

如果以上方案都不行，可以手动下载模型：

1. 访问 Hugging Face 镜像：https://hf-mirror.com/openai/whisper-large-v3-turbo
2. 下载所有文件到本地目录，例如：`C:\models\whisper-large-v3-turbo`
3. 修改 `app/services/whisper.py`，使用本地路径：
   ```python
   self.model = WhisperModel(
       "C:/models/whisper-large-v3-turbo",  # 使用本地路径
       device="cpu",
       compute_type="int8",
       cpu_threads=8,
       num_workers=1
   )
   ```

## 模型大小参考

| 模型 | 大小 | 下载时间（正常网络） |
|------|------|---------------------|
| tiny | ~75MB | 1-2分钟 |
| base | ~150MB | 2-3分钟 |
| small | ~500MB | 5-10分钟 |
| large-v3-turbo | ~1.5GB | 15-30分钟 |

## 验证设置

设置完成后，重新启动项目，查看日志：
- 如果看到 "正在加载模型: xxx"，说明开始下载
- 如果看到 "模型 xxx 加载成功"，说明下载完成
- 如果仍然报错，请检查网络连接或尝试其他方案

## 常见问题

**Q: 遇到 429 错误怎么办？**
A: 
1. 优先使用 Hugging Face Token（方案 1）
2. 或等待 10-30 分钟后重试
3. 或使用代理/VPN 更换 IP

**Q: 使用镜像后仍然无法下载？**
A: 尝试清除缓存：删除 `C:\Users\<用户名>\.cache\huggingface\` 目录，然后重新下载

**Q: Token 安全吗？**
A: 是的，使用 Read 权限的 token 只能读取模型，不能修改或删除任何内容，非常安全

**Q: 如何知道模型下载到哪里了？**
A: 默认位置：`C:\Users\<用户名>\.cache\huggingface\hub\`

**Q: 可以离线使用吗？**
A: 可以！模型下载一次后，会缓存在本地，之后可以完全离线使用

