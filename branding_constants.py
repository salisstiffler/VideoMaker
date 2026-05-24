# branding_constants.py
"""
项目品牌常量定义文件。
用于全局管理视频渲染所需的视觉元素和动画参数，确保跨模块风格一致性。
"""

# ==========================
# 🎨 颜色规范 (Color Palette)
# 基于电光青/霓虹紫的主题，用于所有高光、边框、渐变和强调文本。
# ==========================
COLOR_PRIMARY: str = "#00FFFF"  # 电光青 - 用于核心焦点、能量流等
COLOR_SECONDARY: str = "#BF00FF" # 霓虹紫 - 用于辅助元素、次要高亮

# 背景颜色应使用极深的黑或深蓝，以最大化荧光色的对比度。
GLOBAL_BG_COLOR: str = "#030712"


# ==========================
# ✒️ 字体规范 (Typography)
# 应选用具备未来感、几何感的无衬线字体族。
# 这些需要在渲染引擎（如 FFmpeg/Video Library）的底层配置中指定。
# ==========================
FONT_FAMILY: str = "Orbitron, sans-serif" # Placeholder for a sci-fi font

# 文本渐变颜色对 (用于关键标题和信息提示)
TITLE_GRADIENT: tuple[str, str] = ("#00FFFF", "#BF00FF")


# ==========================
# 🎬 Logo动画规范 (Logo Animation Sequence)
# 定义一个标准的、高冲击力的展示序列。
# 所有Intro/Outro模块必须遵循此结构。
# ==========================

class LogoSequence:
    """定义Logo从显示到退场的标准化时间轴和视觉效果。"""
    # 阶段1: 入场 (Entrance) - 从微光或缩小状态快速放大，增加冲击力。
    ENTRY_DURATION: float = 0.5  # 进入动画时长 (秒)
    ENTRY_EFFECT: str = "SCALE_IN + FLASH" # 效果描述

    # 阶段2: 展示维持 (Hold) - Logo处于全亮、稳定展示状态的时间。
    HOLD_MIN_DURATION: float = 1.5  # 最短保持时间，确保观众能看清Logo
    HOLD_MAX_DURATION: float = 3.0  # 最大保持时间

    # 阶段3: 退场 (Exit) - 不应突兀地消失，而应以能量消散或渐变方式离开。
    EXIT_DURATION: float = 1.0 # 退出动画时长 (秒)
    EXIT_EFFECT: str = "ENERGY_DISSOLVE" # 效果描述

# ==========================
# ⚙️ 通用渲染参数 (Global Rendering Parameters)
# ==========================
DEFAULT_TRANSITION_DURATION: float = 0.8 # 所有画面切换的默认过渡时间（秒）
TITLE_FONT_SIZE_START: int = 72          # 标题字号起始点，用于缩放动画计算

