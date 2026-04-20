"""sprite_packer / symbol_collector のユニットテスト（QGIS環境が必要）"""

import json

import pytest
from qgis.PyQt.QtCore import QSize
from qgis.PyQt.QtGui import QColor, QImage, QPainter


@pytest.mark.usefixtures("qgis_plugin_path")
class TestTrimAndFit:
    """_trim_and_fit が透明余白をトリムし、max_size内にフィットさせること"""

    def _get_fn(self):
        from plugin_dir.kumoy.map_assets.symbol_collector import _trim_and_fit

        return _trim_and_fit

    def _make_image(self, width: int, height: int) -> QImage:
        """指定サイズの透明画像を作成する。"""
        img = QImage(QSize(width, height), QImage.Format_ARGB32)
        img.fill(QColor(0, 0, 0, 0))
        return img

    def _draw_rect(
        self, img: QImage, x: int, y: int, w: int, h: int, color: QColor
    ) -> None:
        """画像上に矩形を描画する。"""
        painter = QPainter(img)
        painter.fillRect(x, y, w, h, color)
        painter.end()

    def test_trims_transparent_margin(self):
        """余白がトリムされ、中央の不透明部分だけが残ること。"""
        img = self._make_image(100, 100)
        # 中央に 20x20 の不透明矩形を描画
        self._draw_rect(img, 40, 40, 20, 20, QColor(255, 0, 0, 255))

        result = self._get_fn()(img, 64)
        # トリム後のアスペクト比は正方形（元が正方形部分）
        assert result.width() == result.height()
        # max_size=64 にフィットしているはず
        assert result.height() == 64

    def test_fits_to_max_size(self):
        """画像がmax_size内に収まること。"""
        img = self._make_image(200, 200)
        self._draw_rect(img, 0, 0, 200, 200, QColor(0, 255, 0, 255))

        result = self._get_fn()(img, 32)
        assert result.width() <= 32
        assert result.height() <= 32

    def test_non_square_aspect_ratio(self):
        """縦長画像がアスペクト比を維持したまま縮小されること。"""
        img = self._make_image(200, 200)
        # 縦長の不透明領域を描画: 20x100
        self._draw_rect(img, 90, 50, 20, 100, QColor(0, 0, 255, 255))

        result = self._get_fn()(img, 64)
        # 高さは64にフィット
        assert result.height() == 64
        # 幅は高さより小さい（縦長なので）
        assert result.width() < result.height()

    def test_fully_transparent_image(self):
        """完全に透明な画像でもエラーにならないこと。"""
        img = self._make_image(100, 100)

        result = self._get_fn()(img, 64)
        assert not result.isNull()
        assert result.width() <= 64
        assert result.height() <= 64

    def test_horizontal_image(self):
        """横長画像が正しくフィットすること。"""
        img = self._make_image(200, 200)
        # 横長の不透明領域を描画: 100x20
        self._draw_rect(img, 50, 90, 100, 20, QColor(255, 255, 0, 255))

        result = self._get_fn()(img, 64)
        # 高さは64にフィット（高さ基準でスケール）
        assert result.height() == 64
        # 幅は高さより大きい（横長なので）
        assert result.width() > result.height()


@pytest.mark.usefixtures("qgis_plugin_path")
class TestPackSprites:
    """pack_sprites がMapLibre互換のスプライトアトラスを生成すること"""

    def _get_fn(self):
        from plugin_dir.kumoy.map_assets.sprite_packer import pack_sprites

        return pack_sprites

    def _make_sprite_entry(self, name: str, width: int, height: int):
        from plugin_dir.kumoy.map_assets.symbol_collector import SpriteEntry

        img = QImage(QSize(width, height), QImage.Format_ARGB32)
        img.fill(QColor(255, 0, 0, 255))
        return SpriteEntry(name=name, image=img)

    def test_single_sprite(self):
        """1つのスプライトでJSON/PNGが正しく生成されること。"""
        entry = self._make_sprite_entry("icon_0", 32, 32)
        json_bytes, png_bytes = self._get_fn()([entry])

        sprite_json = json.loads(json_bytes)
        assert "icon_0" in sprite_json
        assert sprite_json["icon_0"]["width"] == 32
        assert sprite_json["icon_0"]["height"] == 32
        assert sprite_json["icon_0"]["x"] == 0
        assert sprite_json["icon_0"]["y"] == 0
        assert sprite_json["icon_0"]["pixelRatio"] == 1

        # PNGバイト列が有効であること（PNGシグネチャ）
        assert png_bytes[:8] == b"\x89PNG\r\n\x1a\n"

    def test_multiple_sprites(self):
        """複数のスプライトが全てJSONに含まれること。"""
        entries = [
            self._make_sprite_entry("a_0", 16, 16),
            self._make_sprite_entry("b_0", 24, 24),
            self._make_sprite_entry("c_0", 32, 32),
        ]
        json_bytes, png_bytes = self._get_fn()(entries)

        sprite_json = json.loads(json_bytes)
        assert len(sprite_json) == 3
        assert "a_0" in sprite_json
        assert "b_0" in sprite_json
        assert "c_0" in sprite_json

    def test_sprites_no_overlap(self):
        """スプライト同士が重ならないこと。"""
        entries = [self._make_sprite_entry(f"s_{i}", 32, 32) for i in range(5)]
        json_bytes, _ = self._get_fn()(entries)
        sprite_json = json.loads(json_bytes)

        rects = []
        for info in sprite_json.values():
            rects.append(
                (
                    info["x"],
                    info["y"],
                    info["x"] + info["width"],
                    info["y"] + info["height"],
                )
            )

        # 全ペアで重なりがないことを確認
        for i in range(len(rects)):
            for j in range(i + 1, len(rects)):
                x1_min, y1_min, x1_max, y1_max = rects[i]
                x2_min, y2_min, x2_max, y2_max = rects[j]
                overlaps = (
                    x1_min < x2_max
                    and x1_max > x2_min
                    and y1_min < y2_max
                    and y1_max > y2_min
                )
                assert not overlaps, f"Sprites {i} and {j} overlap"

    def test_empty_sprites(self):
        """空リストでも空JSONが返ること。"""
        json_bytes, png_bytes = self._get_fn()([])
        sprite_json = json.loads(json_bytes)
        assert sprite_json == {}

    def test_row_wrap(self):
        """SPRITE_ATLAS_MAX_WIDTHを超えると次の行に折り返すこと。"""
        from plugin_dir.kumoy.map_assets.sprite_packer import SPRITE_ATLAS_MAX_WIDTH

        # 1行に収まりきらないサイズのスプライトを並べる
        sprite_w = 200
        count = (SPRITE_ATLAS_MAX_WIDTH // sprite_w) + 2
        entries = [
            self._make_sprite_entry(f"s_{i}", sprite_w, 50) for i in range(count)
        ]
        json_bytes, _ = self._get_fn()(entries)
        sprite_json = json.loads(json_bytes)

        # 少なくとも1つは y > 0 のスプライトがあるはず
        y_values = [info["y"] for info in sprite_json.values()]
        assert max(y_values) > 0, "No row wrapping occurred"


@pytest.mark.usefixtures("qgis_plugin_path")
class TestImageToPngBytes:
    """_image_to_png_bytes がQImageを有効なPNGバイト列に変換すること"""

    def _get_fn(self):
        from plugin_dir.kumoy.map_assets.sprite_packer import _image_to_png_bytes

        return _image_to_png_bytes

    def test_valid_png(self):
        """出力がPNGシグネチャで始まること。"""
        img = QImage(QSize(10, 10), QImage.Format_ARGB32)
        img.fill(QColor(255, 0, 0, 255))

        result = self._get_fn()(img)
        assert isinstance(result, bytes)
        assert len(result) > 0
        assert result[:8] == b"\x89PNG\r\n\x1a\n"

    def test_roundtrip(self):
        """PNGバイト列からQImageに復元できること。"""
        img = QImage(QSize(20, 15), QImage.Format_ARGB32)
        img.fill(QColor(0, 128, 255, 255))

        png_bytes = self._get_fn()(img)
        restored = QImage()
        restored.loadFromData(png_bytes, "PNG")

        assert restored.width() == 20
        assert restored.height() == 15


@pytest.mark.usefixtures("qgis_plugin_path")
class TestPackImages:
    """_pack_images がJSON辞書とアトラス画像を正しく生成すること"""

    def _get_fn(self):
        from plugin_dir.kumoy.map_assets.sprite_packer import _pack_images

        return _pack_images

    def _make_sprite_entry(self, name: str, width: int, height: int):
        from plugin_dir.kumoy.map_assets.symbol_collector import SpriteEntry

        img = QImage(QSize(width, height), QImage.Format_ARGB32)
        img.fill(QColor(0, 255, 0, 255))
        return SpriteEntry(name=name, image=img)

    def test_atlas_dimensions(self):
        """アトラス画像がスプライトを包含するサイズであること。"""
        entries = [
            self._make_sprite_entry("a", 30, 40),
            self._make_sprite_entry("b", 50, 20),
        ]
        sprite_json, atlas = self._get_fn()(entries)

        # アトラスが全スプライトを包含するサイズ
        for info in sprite_json.values():
            assert info["x"] + info["width"] <= atlas.width()
            assert info["y"] + info["height"] <= atlas.height()

    def test_empty_returns_empty_image(self):
        """空リストで空のQImageが返ること。"""
        sprite_json, atlas = self._get_fn()([])
        assert sprite_json == {}
        assert atlas.isNull()
