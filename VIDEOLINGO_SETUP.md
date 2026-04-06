## VideoLingo 集成配置指南

### 快速配置（在 main.py 顶部修改）

```python
VL_CONFIG = {
    "tts_method": "edge_tts",       # TTS 引擎选择（见下表）
    "whisper_language": "en",       # 源视频语言
    "target_language": "简体中文",   # 翻译目标语言
    "llm_api_key": "sk-xxx",        # LLM API Key（用于翻译）
    "llm_base_url": "https://api.deepseek.com",
    "llm_model": "deepseek-chat",
    "enable_dubbing": True,         # 是否生成配音
}
```

### TTS 引擎选择对比

| tts_method | 费用 | 所需配置 | 音质 |
|---|---|---|---|
| `edge_tts` | 🆓 免费 | 无需配置 | ⭐⭐⭐ |
| `azure_tts` | 💰 需302.ai | `azure_tts.api_key` | ⭐⭐⭐⭐⭐ |
| `sf_fish_tts` | 💰 需SF账号 | `sf_fish_tts.api_key` | ⭐⭐⭐⭐⭐ |
| `openai_tts` | 💰 需302.ai | `openai_tts.api_key` | ⭐⭐⭐⭐ |
| `gpt_sovits` | 🆓 本地 | 需单独安装服务 | ⭐⭐⭐⭐⭐ |

### 修改 API Key（以 Azure 为例）

1. 编辑 `vl_config_template.yaml`：
```yaml
tts_method: 'azure_tts'
azure_tts:
  api_key: 'YOUR_302_API_KEY'
  voice: 'zh-CN-YunfengNeural'   # 男声
  # voice: 'zh-CN-XiaoxiaoNeural'  # 女声
```

2. 在 `main.py` 设置：
```python
VL_CONFIG["tts_method"] = "azure_tts"
```

### Edge-TTS 常用中文声音

| voice | 性别 | 风格 |
|---|---|---|
| `zh-CN-YunxiNeural` | 男 | 自然通用 |
| `zh-CN-YunfengNeural` | 男 | 新闻播报 |
| `zh-CN-XiaoxiaoNeural` | 女 | 自然通用 |
| `zh-CN-XiaoyiNeural` | 女 | 活泼 |

修改 `vl_config_template.yaml` 中：
```yaml
edge_tts:
  voice: 'zh-CN-YunxiNeural'
```

### LLM 翻译配置

推荐使用 DeepSeek（便宜且中文效果好）：
```yaml
api:
  key: 'sk-your-deepseek-key'
  base_url: 'https://api.deepseek.com'
  model: 'deepseek-chat'
```

也支持 OpenAI / Claude（通过代理）：
```yaml
api:
  key: 'sk-xxx'
  base_url: 'https://api.openai.com/v1'
  model: 'gpt-4o-mini'
```

### 常见问题

**Q: 运行时报 VL 路径不存在？**  
```powershell
git clone https://github.com/Huanshere/VideoLingo.git d:\VideoLingo
cd d:\VideoLingo
python setup_env.py
```

**Q: 降级到旧模式（F5-TTS）怎么做？**  
在 `main.py` 设置 `VL_CONFIG["enable_dubbing"] = False`，或直接删除 `my_voice.wav`。

**Q: 源视频是中文，翻译到英文怎么设置？**  
```python
VL_CONFIG["whisper_language"] = "zh"
VL_CONFIG["target_language"] = "English"
```
