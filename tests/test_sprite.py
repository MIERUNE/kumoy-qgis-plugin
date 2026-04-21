"""sprite_packer / symbol_collector のユニットテスト（QGIS環境が必要）"""

import json

import pytest
from plugin_dir.pyqt_version import Q_IMAGE_FORMAT
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
        img = QImage(QSize(width, height), Q_IMAGE_FORMAT.Format_ARGB32)
        img.fill(QColor(0, 0, 0, 0))
        return img

    def _draw_rect(
        self, img: QImage, x: int, y: int, w: int, h: int, color: QColor
    ) -> None:
        """画像上に矩形を描画する。"""
        painter = QPainter(img)
        painter.fillRect(x, y, w, h, color)
        painter.end()

    def _alpha_at(self, img: QImage, x: int, y: int) -> int:
        """画像の指定座標のアルファ値を取得する。"""
        img32 = img.convertToFormat(Q_IMAGE_FORMAT.Format_ARGB32)
        stride = img32.bytesPerLine()
        buf = img32.constBits().asstring(stride * img32.height())
        return buf[y * stride + x * 4 + 3]

    def test_trims_transparent_margin(self):
        """余白がトリムされ、シンボル高さが max_size に揃うこと。"""
        img = self._make_image(100, 100)
        # 20x20 の不透明矩形を画像中心に配置。tight bbox が正方形なので
        # スケール後も正方形、かつ中心一致のためキャンバスも正方形。
        self._draw_rect(img, 40, 40, 20, 20, QColor(255, 0, 0, 255))

        result = self._get_fn()(img, 64)
        # 高さは max_size に固定
        assert result.height() == 64
        # tight bbox が正方形かつ中心対称のため、幅も max_size
        assert result.width() == 64

    def test_fits_to_max_size(self):
        """入力がキャンバスを埋め尽くしていても高さは max_size に揃うこと。"""
        img = self._make_image(200, 200)
        self._draw_rect(img, 0, 0, 200, 200, QColor(0, 255, 0, 255))

        result = self._get_fn()(img, 32)
        # tight bbox が正方形かつ画像中心と一致するので幅高さ共に max_size
        assert result.width() == 32
        assert result.height() == 32

    def test_non_square_aspect_ratio(self):
        """縦長画像はシンボル高さ基準でスケールされ、高さが max_size になること。"""
        img = self._make_image(200, 200)
        # 20x100 の縦長矩形を画像中心に配置
        self._draw_rect(img, 90, 50, 20, 100, QColor(0, 0, 255, 255))

        result = self._get_fn()(img, 64)
        assert result.height() == 64
        # 縦長なので幅は高さより小さい
        assert result.width() < result.height()

    def test_fully_transparent_image(self):
        """完全に透明な画像でも max_size x max_size のキャンバスが返ること。"""
        img = self._make_image(100, 100)

        result = self._get_fn()(img, 64)
        assert not result.isNull()
        assert result.width() == 64
        assert result.height() == 64

    def test_horizontal_image_preserves_aspect(self):
        """横長画像はシンボル高さが max_size に揃い、幅は自然アスペクト比に従うこと。

        クライアント側は icon-size = 実寸 / max_size で計算するため、
        スプライト内のシンボル高さは max_size に一致する必要がある。
        横長シンボルは幅が max_size を超えても、高さ方向で基準化する。
        """
        img = self._make_image(400, 200)
        # 100x20 の横長矩形を画像中心に配置
        self._draw_rect(img, 150, 90, 100, 20, QColor(255, 255, 0, 255))

        result = self._get_fn()(img, 64)
        # 高さは max_size に固定
        assert result.height() == 64
        # 横長の自然アスペクト比が保たれ、幅は高さを大きく上回る
        assert result.width() > result.height()

    def test_offset_symbol_preserves_center(self):
        """シンボルが画像中心からオフセットしていても、出力キャンバスの中心が
        元画像の中心に対応し、シンボル高さは max_size に保たれること。

        シンボル中心（bbox中心）ではなく元画像中心を不変にするため、
        オフセットが大きい側の反対側は透明パディングで補う。
        """
        img = self._make_image(100, 100)
        # 10x10 の矩形を画像中心 (50,50) から大きく左にオフセット。
        # シンボルbbox: (20,45)-(29,54), 中心 (25, 50)。
        # 画像中心からのオフセット: x方向 -25px。
        self._draw_rect(img, 20, 45, 10, 10, QColor(255, 0, 0, 255))

        result = self._get_fn()(img, 64)
        # 縦方向は対称オフセットなので高さは max_size
        assert result.height() == 64
        # x方向オフセットが大きく、反対側に透明パディングが入るため
        # キャンバス幅は max_size を大きく上回る
        assert result.width() > 64

        # 中心不変性: シンボルが左側に寄っているので、キャンバス右端は透明
        w = result.width()
        h = result.height()
        for y in range(h):
            assert self._alpha_at(result, w - 1, y) == 0
        # 逆に、シンボルが配置されている左端は非透明ピクセルを含む
        assert any(self._alpha_at(result, 0, y) != 0 for y in range(h))

    def test_vertical_offset_symbol_preserves_center(self):
        """縦方向オフセットでも元画像中心を基準にキャンバス中心が配置されること。"""
        img = self._make_image(100, 100)
        # 10x10 の矩形を画像中心 (50,50) から下にオフセット。
        # シンボルbbox: (45,70)-(54,79), 中心 (50, 75)。
        self._draw_rect(img, 45, 70, 10, 10, QColor(0, 255, 0, 255))

        result = self._get_fn()(img, 64)
        # 縦オフセットが大きいため、キャンバス高さは max_size を超える
        assert result.height() > 64
        # x方向は対称なので幅は max_size
        assert result.width() == 64

        # シンボルは下寄りに配置されているので、キャンバス上端は透明
        w = result.width()
        for x in range(w):
            assert self._alpha_at(result, x, 0) == 0
        # シンボルの配置されている下端は非透明
        assert any(
            self._alpha_at(result, x, result.height() - 1) != 0 for x in range(w)
        )


@pytest.mark.usefixtures("qgis_plugin_path")
class TestPackSprites:
    """pack_sprites がMapLibre互換のスプライトアトラスを生成すること"""

    def _get_fn(self):
        from plugin_dir.kumoy.map_assets.sprite_packer import pack_sprites

        return pack_sprites

    def _make_sprite_entry(self, name: str, width: int, height: int):
        from plugin_dir.kumoy.map_assets.symbol_collector import SpriteEntry

        img = QImage(QSize(width, height), Q_IMAGE_FORMAT.Format_ARGB32)
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
        img = QImage(QSize(10, 10), Q_IMAGE_FORMAT.Format_ARGB32)
        img.fill(QColor(255, 0, 0, 255))

        result = self._get_fn()(img)
        assert isinstance(result, bytes)
        assert len(result) > 0
        assert result[:8] == b"\x89PNG\r\n\x1a\n"

    def test_roundtrip(self):
        """PNGバイト列からQImageに復元できること。"""
        img = QImage(QSize(20, 15), Q_IMAGE_FORMAT.Format_ARGB32)
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

        img = QImage(QSize(width, height), Q_IMAGE_FORMAT.Format_ARGB32)
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
