from translator_timing import translate_with_timing

def run_tests():
    print("Testing translation connected to LM Studio (Qwen)...")
    
    # 场景1：较短发音，中文精简意译
    text1 = "You know, this is absolutely incredible. I can't believe it."
    duration1 = 2.5
    print(f"\n[Test 1] (duration: {duration1}s)")
    print(f"Original Text: {text1}")
    result1 = translate_with_timing(text1, duration1)
    print(f"Result (Should be ~11 chars): {result1}")
    print(f"Actual Character Count: {len(result1)}")

    # 场景2：包含大量废话拉长时间的句子（或者语速较慢），需要扩写中文
    text2 = "Soooooo, uh, I guess what I'm trying to say is that we should probably just go ahead and proceed with the initial plan."
    duration2 = 6.0
    print(f"\n[Test 2] (duration: {duration2}s, slow speaker)")
    print(f"Original Text: {text2}")
    result2 = translate_with_timing(text2, duration2)
    print(f"Result (Should be ~27 chars): {result2}")
    print(f"Actual Character Count: {len(result2)}")

    # 场景3：语速极快的短句子
    text3 = "Wait, let's stop for a second."
    duration3 = 1.0
    print(f"\n[Test 3] (duration: {duration3}s, fast speaker)")
    print(f"Original Text: {text3}")
    result3 = translate_with_timing(text3, duration3)
    print(f"Result (Should be ~4-5 chars): {result3}")
    print(f"Actual Character Count: {len(result3)}")

if __name__ == "__main__":
    # 需要提前启动 LM Studio，否则会报错 Connection Refused
    run_tests()
