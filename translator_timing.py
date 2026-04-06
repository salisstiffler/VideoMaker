import os
import re
from openai import OpenAI

# 默认配置本地 LM Studio
LM_STUDIO_BASE_URL = "http://localhost:1234/v1"
LM_STUDIO_API_KEY = "lm-studio"
MODEL_NAME = "qwen2.5-7b-instruct" # 或其他你部署好的模型名叫什么填什么

def get_client():
    """获取 OpenAI 客户端对象，指向本地 LM Studio"""
    return OpenAI(
        base_url=LM_STUDIO_BASE_URL,
        api_key=LM_STUDIO_API_KEY
    )

def translate_with_timing(text: str, duration: float, chars_per_sec: float = 3.8, context: str = "") -> str:
    """
    根据原视频片段时长进行限长意译，支持上下文参考。
    chars_per_sec 默认下调至 3.8，确保配音从容。
    """
    client = get_client()

    # 估算目标字数上下界
    target_chars = int(duration * chars_per_sec)
    # 对于极短句，给予更严苛的限制
    if duration < 2.0:
        min_chars = 1
        max_chars = max(2, int(duration * 3.5)) # 短句语速要求更慢
    else:
        min_chars = max(1, int(target_chars * 0.6))
        max_chars = int(target_chars * 1.1) # 严格控制上限

    system_prompt = (
        "你是一个顶级的影视翻译官和配音导演。\n"
        "你的目标是将英文台词翻译成中文，必须让配音员在指定时间内读完，绝对不能太长！\n"
        "如果原文很长但给的时间很少，你必须进行大幅度删减，只保留核心意思。\n"
    )

    brevity_note = ""
    if duration < 2.5:
        brevity_note = "【特别注意】: 这句话时间极短，请务必使用极其简短的词语，哪怕只用2-3个字！\n"

    user_prompt = ""
    if context:
        user_prompt += f"【前文背景】: \n{context}\n\n"

    user_prompt += (
        f"【原文】: {text}\n"
        f"【可用时长】: {duration:.2f} 秒\n"
        f"{brevity_note}"
        f"【字数严限】: 必须控制在 {min_chars} 到 {max_chars} 个汉字之间（不含标点）。\n"
        "直接输出翻译台词，不要解释："
    )

    
    try:
        response = client.chat.completions.create(
            model=MODEL_NAME,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.7,
            max_tokens=200
        )
        result = response.choices[0].message.content.strip()
        result = result.strip('"').strip("'").replace('\n', ' ')
        return result
    except Exception as e:
        print(f"[Error] Translation failed: {e}")
        return ""

def batch_translate_with_context(segments: list, chars_per_sec: float = 4.5):
    """
    批量翻译台词，并自动维护前两句作为上下文。
    segments: [(start, end, text), ...]
    """
    results = []
    context_window = [] # 存储最近两句的 (原文, 译文)
    
    for i, (sts, ets, text) in enumerate(segments):
        dur = ets - sts
        if dur < 0.3 or not text.strip():
            results.append("")
            continue
            
        # 构建上下文字符串
        context_str = ""
        for prev_src, prev_trans in context_window:
            context_str += f"原句: {prev_src} -> 译文: {prev_trans}\n"
            
        print(f"  [翻译 {i+1}/{len(segments)}] {dur:.1f}s | {text}")
        zh_text = translate_with_timing(text, dur, chars_per_sec, context=context_str)
        print(f"  -> {zh_text}")
        
        results.append(zh_text)
        
        # 更新滑动窗口
        context_window.append((text, zh_text))
        if len(context_window) > 2:
            context_window.pop(0)
            
    return results
