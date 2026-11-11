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
    QgsProperty,
    QgsRasterFillSymbolLayer,
    QgsRasterLineSymbolLayer,
    QgsRasterMarkerSymbolLayer,
    QgsRendererCategory,
    QgsSingleSymbolRenderer,
    QgsSVGFillSymbolLayer,
    QgsSvgMarkerSymbolLayer,
    QgsSymbolLayer,
    QgsSymbolLayerUtils,
    QgsVectorLayer,
)
from qgis.PyQt.QtCore import QSize
from qgis.PyQt.QtGui import QColor, QImage, QPainter


@pytest.mark.usefixtures("qgis_plugin_path")
class TestTrim:
    """_trim が画像中心を保ったまま透明余白を切り落とすこと（拡大縮小はしない）"""

    def _trim(self, img: QImage) -> QImage:
        from plugin_dir.kumoy.sprite.symbol_collector import _trim

        return _trim(img)

    def _image_with_rect(self, x: int, y: int, w: int, h: int) -> QImage:
        img = QImage(QSize(100, 100), Q_IMAGE_FORMAT.Format_ARGB32)
        img.fill(QColor(0, 0, 0, 0))
        painter = QPainter(img)
        painter.fillRect(x, y, w, h, QColor(255, 0, 0, 255))
        painter.end()
        return img

    def test_trims_to_content_without_scaling(self):
        result = self._trim(self._image_with_rect(40, 45, 20, 10))
        assert (result.width(), result.height()) == (20, 10)

    def test_offset_symbol_keeps_the_image_center(self):
        # Content 25 px left of the center: padded on the right to keep the anchor
        result = self._trim(self._image_with_rect(20, 45, 10, 10))
        assert (result.width(), result.height()) == (60, 10)
        assert result.pixelColor(0, 5).alpha() > 0
        assert result.pixelColor(59, 5).alpha() == 0

    def test_fully_transparent_image(self):
        result = self._trim(self._image_with_rect(0, 0, 0, 0))
        assert not result.isNull()


@pytest.mark.usefixtures("qgis_plugin_path")
class TestRender:
    """_render がシンボルを実寸で、回転を焼き込まずに描くこと"""

    def _sprite(self, symbol: QgsMarkerSymbol) -> QImage:
        from plugin_dir.kumoy.sprite.symbol_collector import _render, _trim

        return _trim(_render(symbol))

    def _marker(self, **props) -> QgsMarkerSymbol:
        return QgsMarkerSymbol.createSimple({"outline_style": "no", **props})

    @pytest.mark.parametrize(
        "unit, size, expected_px",
        [
            # 72 dpi as in the style converter, times SPRITE_PIXEL_RATIO (2)
            ("MM", "10", 10 * 72 / 25.4 * 2),
            ("Point", "10", 20),
            ("Pixel", "10", 20),
        ],
    )
    def test_real_size(self, unit, size, expected_px):
        image = self._sprite(self._marker(name="square", size=size, size_unit=unit))
        # +-1 px of antialiasing per side
        assert abs(image.height() - expected_px) <= 2

    @pytest.mark.parametrize("name", ["circle", "triangle", "star", "square"])
    def test_angle_is_not_baked(self, name):
        """The reported bug: a rotated symbol grew on the web map."""
        upright = self._sprite(self._marker(name=name, size="10"))
        rotated = self._sprite(self._marker(name=name, size="10", angle="45"))
        assert rotated == upright

    def test_data_defined_angle_is_not_baked(self):
        """An expression that evaluates without a feature must not be baked in either."""
        upright = self._sprite(self._marker(name="triangle", size="10"))
        rotated = self._marker(name="triangle", size="10", angle="30")
        rotated.symbolLayer(0).setDataDefinedProperty(
            QgsSymbolLayer.Property.Angle, QgsProperty.fromExpression("45")
        )
        assert self._sprite(rotated) == upright

    def test_edges_are_antialiased(self):
        """The reported bug: simple markers came out jagged on the web map."""
        image = self._sprite(self._marker(name="circle", size="6"))
        alphas = {
            image.pixelColor(x, y).alpha()
            for x in range(image.width())
            for y in range(image.height())
        }
        assert any(0 < a < 255 for a in alphas)

    def test_does_not_modify_the_symbol(self):
        symbol = self._marker(name="square", angle="45")
        self._sprite(symbol)
        assert symbol.angle() == 45


@pytest.mark.usefixtures("qgis_plugin_path")
class TestSymbolSprites:
    """シンボルレイヤーごとに、そのレイヤーだけを描いた画像になること"""

    def _sprites(self, symbol: QgsMarkerSymbol) -> list:
        from plugin_dir.kumoy.sprite.symbol_collector import _symbol_sprites

        return _symbol_sprites("L_0", symbol)

    def _symbol(self, *names) -> QgsMarkerSymbol:
        return QgsMarkerSymbol(
            [
                QgsMarkerSymbol.createSimple({"name": n}).takeSymbolLayer(0)
                for n in names
            ]
        )

    def test_one_sprite_per_layer(self):
        """The reported bug: a data-defined angle on one layer rotated the whole
        symbol on the web map, because the symbol was drawn as one image."""
        sprites = self._sprites(self._symbol("triangle", "square"))
        assert [s.name for s in sprites] == ["L_0_0", "L_0_1"]
        assert sprites[1].image == self._sprites(self._symbol("square"))[0].image

    def test_each_layer_angle_is_not_baked(self):
        from plugin_dir.kumoy.sprite.symbol_collector import _render, _trim

        symbol = self._symbol("triangle", "triangle")
        symbol.symbolLayer(1).setAngle(45)
        sprites = self._sprites(symbol)
        upright = _trim(_render(self._symbol("triangle")))
        assert sprites[0].image == upright
        assert sprites[1].image == upright


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
        assert sprite_json["icon_0"]["pixelRatio"] == 2

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
        from plugin_dir.kumoy.sprite import embed_local_symbol_files

        embed_local_symbol_files(project)

    def _increase(self, project):
        from plugin_dir.kumoy.sprite import embedding_size_increase

        return embedding_size_increase(project)

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

        # Read the symbol back from the layer, as the canvas does.
        layer = next(iter(project.mapLayers().values()))
        embedded = layer.renderer().symbol()
        assert embedded.symbolLayer(0).path().startswith("base64:")
        assert embedded.asImage(QSize(64, 64)) == image

    def test_svg_fill_keeps_its_colours(self, project, svg_file):
        # Non-default values: setSvgFilePath() resets them to the SVG's own defaults.
        symbol_layer = QgsSVGFillSymbolLayer(str(svg_file))
        symbol_layer.setSvgFillColor(QColor(10, 20, 30))
        symbol_layer.setSvgStrokeColor(QColor(40, 50, 60))
        symbol_layer.setSvgStrokeWidth(3.5)
        self._add_layer(project, QgsFillSymbol([symbol_layer]))
        before = symbol_layer.properties()

        self._embed(project)

        after = symbol_layer.properties()
        assert {k for k in before if before[k] != after[k]} == {"svgFile"}

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

        assert self._increase(project) == 0
        self._embed(project)
        assert symbol_layer.path() == path

    def test_increase_only_with_a_file_symbol(self, project, png_file):
        self._add_layer(project, QgsMarkerSymbol.createSimple({}), name="plain")
        assert self._increase(project) == 0

        self._add_layer(
            project,
            QgsMarkerSymbol([QgsRasterMarkerSymbolLayer(str(png_file))]),
            name="with file",
        )
        assert self._increase(project) > 0

    def test_increase_changes_nothing(self, project, tmp_path, png_file):
        symbol_layer = QgsRasterMarkerSymbolLayer(str(png_file))
        self._add_layer(project, QgsMarkerSymbol([symbol_layer]))
        before = self._write(project, tmp_path)

        assert self._increase(project) > 0

        after = self._write(project, tmp_path)
        assert symbol_layer.path() == str(png_file)
        assert _file_values(after) == _file_values(before)
        assert _canonical_without_file_values(after) == _canonical_without_file_values(
            before
        )

    def test_nothing_left_after_embedding(self, project, png_file):
        self._add_layer(
            project, QgsMarkerSymbol([QgsRasterMarkerSymbolLayer(str(png_file))])
        )

        self._embed(project)

        assert self._increase(project) == 0

    def test_increase_predicts_the_written_size(
        self, project, tmp_path, svg_file, png_file
    ):
        """The prediction must not fall short of the real growth, or a save could
        be offered embedding and then be refused by the size limit."""
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
        self._add_layer(project, QgsFillSymbol([QgsSVGFillSymbolLayer(str(svg_file))]))
        before = len(self._write(project, tmp_path))
        increase = self._increase(project)

        self._embed(project)

        growth = len(self._write(project, tmp_path)) - before
        assert growth <= increase
        # Off only by the replaced paths, which the prediction does not subtract.
        assert increase - growth < 500

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
