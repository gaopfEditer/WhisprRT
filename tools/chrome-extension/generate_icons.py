#!/usr/bin/env python3
"""
生成 Chrome 插件占位图标
运行: python generate_icons.py
"""

from PIL import Image, ImageDraw, ImageFont
import os

def create_icon(size, output_path):
    """创建指定尺寸的图标"""
    # 创建图像
    img = Image.new('RGB', (size, size), color='#4CAF50')
    draw = ImageDraw.Draw(img)
    
    # 绘制简单的图标（一个播放按钮）
    margin = size // 4
    # 绘制三角形（播放按钮）
    points = [
        (margin, margin),
        (size - margin, size // 2),
        (margin, size - margin)
    ]
    draw.polygon(points, fill='white')
    
    # 保存
    img.save(output_path, 'PNG')
    print(f"✅ 已生成: {output_path} ({size}x{size})")


def main():
    icons_dir = Path(__file__).parent / "icons"
    icons_dir.mkdir(exist_ok=True)
    
    sizes = [16, 48, 128]
    for size in sizes:
        output_path = icons_dir / f"icon{size}.png"
        create_icon(size, output_path)
    
    print(f"\n🎉 所有图标已生成到: {icons_dir.absolute()}")


if __name__ == "__main__":
    from pathlib import Path
    try:
        from PIL import Image, ImageDraw
        main()
    except ImportError:
        print("❌ 需要安装 Pillow 库:")
        print("   pip install Pillow")
        print("\n或者手动创建图标文件（见 icons/README.md）")

