"""sprite_packer / symbol_collector のユニットテスト（QGIS環境が必要）"""

import base64
import json
import xml.etree.ElementTree as ET

import pytest
from plugin_dir.pyqt_version import Q_IMAGE_FORMAT
from qgis.core import (
    QgsCategorizedSymbolRenderer,
    QgsFillSymbol,
    QgsLineSymbol,
    QgsMarkerLineSymbolLayer,
    QgsMarkerSymbol,
    QgsPathResolver,
    QgsProject,
    QgsRasterFillSymbolLayer,
    QgsRasterLineSymbolLayer,
    QgsRasterMarkerSymbolLayer,
    QgsRendererCategory,
    QgsSingleSymbolRenderer,
    QgsSVGFillSymbolLayer,
    QgsSvgMarkerSymbolLayer,
    QgsSymbolLayerUtils,
    QgsVectorLayer,
)
from qgis.PyQt.QtCore import QSize
from qgis.PyQt.QtGui import QColor, QImage, QPainter


@pytest.mark.usefixtures("qgis_plugin_path")
class TestTrimAndFit:
    """_trim_and_fit が透明余白をトリムし、max_size内にフィットさせること"""

    def _get_fn(self):
        from plugin_dir.kumoy.sprite.symbol_collector import _trim_and_fit

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
        from plugin_dir.kumoy.sprite.sprite_packer import pack_sprites

        return pack_sprites

    def _make_sprite_entry(self, name: str, width: int, height: int):
        from plugin_dir.kumoy.sprite.symbol_collector import SpriteEntry

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
        from plugin_dir.kumoy.sprite.sprite_packer import SPRITE_ATLAS_MAX_WIDTH

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
        from plugin_dir.kumoy.sprite.sprite_packer import _image_to_png_bytes

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
        from plugin_dir.kumoy.sprite.sprite_packer import _pack_images

        return _pack_images

    def _make_sprite_entry(self, name: str, width: int, height: int):
        from plugin_dir.kumoy.sprite.symbol_collector import SpriteEntry

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


_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="20" height="10" '
    'viewBox="0 0 20 10"><rect width="20" height="10" fill="param(fill) #ff0000" '
    'stroke="param(outline) #00ff00" stroke-width="param(outline-width) 2"/></svg>'
)

# Independent oracle for the .qgs layout: <layer class=...> -> <Option> holding the path
_FILE_OPTION_KEYS = {
    "SvgMarker": "name",
    "SVGFill": "svgFile",
    "RasterMarker": "imageFile",
    "RasterFill": "imageFile",
    "RasterLine": "imageFile",
}


def _file_options(root: ET.Element) -> list:
    options = []
    for layer in root.iter("layer"):
        key = _FILE_OPTION_KEYS.get(layer.get("class"))
        if key:
            options.append(layer.find(f"Option/Option[@name='{key}']"))
    return options


def _file_values(qgs: str) -> list:
    """Stored path of every file-based symbol layer, in document order."""
    return [o.get("value") for o in _file_options(ET.fromstring(qgs))]


def _canonical_without_file_values(qgs: str) -> str:
    """Canonical XML with the file paths blanked, to compare everything else."""
    root = ET.fromstring(qgs)
    root.attrib.pop("saveDateTime", None)  # differs between two writes
    for option in _file_options(root):
        option.set("value", "")
    return ET.canonicalize(ET.tostring(root, encoding="unicode"), strip_text=True)


def _embedded(data: bytes) -> str:
    return "base64:" + base64.b64encode(data).decode("ascii")


@pytest.mark.usefixtures("qgis_plugin_path")
class TestSymbolEmbedding:
    """ローカルのSVG/画像パスが、プロジェクト内で base64 埋め込みに置き換わること。

    パスのまま保存すると別PCで開いたときにアイコンが消える。
    """

    @pytest.fixture
    def project(self, qgis_app):
        project = QgsProject.instance()
        project.clear()
        yield project
        project.clear()

    @pytest.fixture
    def svg_file(self, tmp_path):
        path = tmp_path / "icon.svg"
        path.write_text(_SVG, encoding="utf-8")
        return path

    @pytest.fixture
    def png_file(self, tmp_path):
        path = tmp_path / "icon.png"
        img = QImage(QSize(8, 4), Q_IMAGE_FORMAT.Format_ARGB32)
        img.fill(QColor(0, 0, 255, 255))
        saved = img.save(str(path))
        assert saved
        return path

    def _add_layer(self, project, symbol, name="layer"):
        geometry = {
            "QgsMarkerSymbol": "Point",
            "QgsLineSymbol": "LineString",
            "QgsFillSymbol": "Polygon",
        }[type(symbol).__name__]
        layer = QgsVectorLayer(f"{geometry}?crs=EPSG:4326", name, "memory")
        layer.setRenderer(QgsSingleSymbolRenderer(symbol))
        project.addMapLayer(layer)
        return layer

    def _write(self, project, tmp_path):
        """The project as QGIS writes it (next to the files, so paths are relative)."""
        path = str(tmp_path / "project.qgs")
        written = project.write(path)
        assert written
        with open(path, encoding="utf-8") as f:
            return f.read()

    def _embed(self, project):
        """Prepare and apply, as the save flows do when the user agrees."""
        from plugin_dir.kumoy.sprite import (
            apply_symbol_embedding,
            prepare_symbol_embedding,
        )

        styles = prepare_symbol_embedding(project)
        apply_symbol_embedding(styles)
        return styles

    def _svg_marker(self, path):
        layer = QgsSvgMarkerSymbolLayer(str(path))
        # Non-default style: setPath() would reset these to the SVG's defaults.
        layer.setFillColor(QColor(10, 20, 30))
        layer.setStrokeColor(QColor(40, 50, 60))
        layer.setStrokeWidth(3.5)
        return layer

    @pytest.mark.parametrize(
        "kind",
        ["svg_marker", "svg_fill", "raster_marker", "raster_fill", "raster_line"],
    )
    def test_file_is_embedded(self, project, tmp_path, svg_file, png_file, kind):
        symbol_layer, symbol, source = {
            "svg_marker": (
                QgsSvgMarkerSymbolLayer(str(svg_file)),
                QgsMarkerSymbol,
                svg_file,
            ),
            "svg_fill": (QgsSVGFillSymbolLayer(str(svg_file)), QgsFillSymbol, svg_file),
            "raster_marker": (
                QgsRasterMarkerSymbolLayer(str(png_file)),
                QgsMarkerSymbol,
                png_file,
            ),
            "raster_fill": (
                QgsRasterFillSymbolLayer(str(png_file)),
                QgsFillSymbol,
                png_file,
            ),
            "raster_line": (
                QgsRasterLineSymbolLayer(str(png_file)),
                QgsLineSymbol,
                png_file,
            ),
        }[kind]
        self._add_layer(project, symbol([symbol_layer]))
        before = self._write(project, tmp_path)
        assert not _file_values(before)[0].startswith("base64:")

        self._embed(project)

        after = self._write(project, tmp_path)
        assert _file_values(after) == [_embedded(source.read_bytes())]
        # Only the path changed: colours, widths, renderer... are untouched.
        assert _canonical_without_file_values(after) == _canonical_without_file_values(
            before
        )

    def test_svg_marker_keeps_its_look(self, project, svg_file):
        symbol = QgsMarkerSymbol([self._svg_marker(svg_file)])
        self._add_layer(project, symbol)
        image = symbol.asImage(QSize(64, 64))

        self._embed(project)

        # The layer got a new renderer: read the symbol back from it.
        layer = next(iter(project.mapLayers().values()))
        embedded = layer.renderer().symbol()
        assert embedded.symbolLayer(0).path().startswith("base64:")
        assert embedded.asImage(QSize(64, 64)) == image

    def test_nested_sub_symbol_is_embedded(self, project, tmp_path, svg_file):
        line_layer = QgsMarkerLineSymbolLayer()
        line_layer.setSubSymbol(
            QgsMarkerSymbol([QgsSvgMarkerSymbolLayer(str(svg_file))])
        )
        self._add_layer(project, QgsLineSymbol([line_layer]))

        self._embed(project)

        assert _file_values(self._write(project, tmp_path)) == [
            _embedded(svg_file.read_bytes())
        ]

    def test_every_category_is_embedded(self, project, tmp_path, png_file):
        categories = [
            QgsRendererCategory(
                i,
                QgsMarkerSymbol([QgsRasterMarkerSymbolLayer(str(png_file))]),
                str(i),
            )
            for i in range(3)
        ]
        layer = QgsVectorLayer("Point?crs=EPSG:4326", "layer", "memory")
        layer.setRenderer(QgsCategorizedSymbolRenderer("id", categories))
        project.addMapLayer(layer)

        self._embed(project)

        # The categorized renderer also keeps a source symbol: 3 categories + 1.
        values = _file_values(self._write(project, tmp_path))
        assert len(values) >= 3
        assert set(values) == {_embedded(png_file.read_bytes())}

    def test_svg_library_name_is_resolved(self, project, tmp_path):
        name = "arrows/Arrow_01.svg"
        resolved = QgsSymbolLayerUtils.svgSymbolNameToPath(name, QgsPathResolver())
        if not resolved or resolved == name:
            pytest.skip(f"{name} is not in this QGIS install's SVG paths")
        self._add_layer(project, QgsMarkerSymbol([QgsSvgMarkerSymbolLayer(name)]))

        self._embed(project)

        with open(resolved, "rb") as f:
            assert _file_values(self._write(project, tmp_path)) == [_embedded(f.read())]

    @pytest.mark.parametrize(
        "path",
        ["", "/nonexistent/dir/icon.png", "base64:aGVsbG8="],
        ids=["empty", "missing", "already-embedded"],
    )
    def test_nothing_to_embed(self, project, path):
        symbol_layer = QgsRasterMarkerSymbolLayer(path)
        self._add_layer(project, QgsMarkerSymbol([symbol_layer]))

        assert self._embed(project) == {}
        assert symbol_layer.path() == path

    def test_remote_url_is_not_treated_as_a_file(self, qgis_app):
        """Calls the helper directly: a symbol layer built on a real URL starts a
        network fetch that crashes QGIS 4 at interpreter shutdown."""
        from plugin_dir.kumoy.sprite.symbol_embedder import _embedded_value

        cache = {}
        url = "https://example.invalid/icon.png"

        assert _embedded_value(url, False, QgsPathResolver(), cache) is None
        # Skipped up front instead of failing to open() it (which would be cached).
        assert cache == {}

    def test_only_layers_with_local_files_are_listed(self, project, png_file):
        with_file = self._add_layer(
            project,
            QgsMarkerSymbol([QgsRasterMarkerSymbolLayer(str(png_file))]),
            name="with file",
        )
        self._add_layer(project, QgsMarkerSymbol.createSimple({}), name="plain")

        from plugin_dir.kumoy.sprite import prepare_symbol_embedding

        assert list(prepare_symbol_embedding(project)) == [with_file]

    def test_prepare_changes_nothing(self, project, tmp_path, png_file):
        from plugin_dir.kumoy.sprite import prepare_symbol_embedding

        symbol_layer = QgsRasterMarkerSymbolLayer(str(png_file))
        self._add_layer(project, QgsMarkerSymbol([symbol_layer]))
        before = self._write(project, tmp_path)

        assert prepare_symbol_embedding(project)

        after = self._write(project, tmp_path)
        assert symbol_layer.path() == str(png_file)
        assert _file_values(after) == _file_values(before)
        assert _canonical_without_file_values(after) == _canonical_without_file_values(
            before
        )

    def test_idempotent(self, project, png_file):
        self._add_layer(
            project, QgsMarkerSymbol([QgsRasterMarkerSymbolLayer(str(png_file))])
        )

        assert self._embed(project) != {}
        assert self._embed(project) == {}

    def test_serialize_project_does_not_embed(self, project, png_file):
        """serialize_project() stays a plain serialization: embedding is opt-in."""
        from plugin_dir.kumoy.local_cache.map import serialize_project

        self._add_layer(
            project, QgsMarkerSymbol([QgsRasterMarkerSymbolLayer(str(png_file))])
        )

        values = _file_values(serialize_project())

        assert len(values) == 1
        assert not values[0].startswith("base64:")

    def test_icon_survives_reopening_without_the_original_file(
        self, project, png_file, tmp_path
    ):
        """The reported bug: the same project opened on a PC that lacks the file."""
        self._add_layer(
            project, QgsMarkerSymbol([QgsRasterMarkerSymbolLayer(str(png_file))])
        )
        self._embed(project)
        saved = tmp_path / "saved.qgs"
        saved.write_text(self._write(project, tmp_path), encoding="utf-8")
        png_file.unlink()

        project.clear()
        read_ok = project.read(str(saved))
        assert read_ok

        layer = next(iter(project.mapLayers().values()))
        image = layer.renderer().symbol().asImage(QSize(32, 32))
        assert image.pixelColor(16, 16).alpha() > 0
