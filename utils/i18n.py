"""
Lightweight dictionary-based i18n.

`tr(source)` returns the Simplified-Chinese rendering of `source` when the
active language is zh_CN, otherwise the source string itself. Unknown
strings pass through unchanged, so untranslated dynamic text is safe.
"""
_LANG = "en"

TRANSLATIONS = {
    # ---- main window ----
    "PDF Bubble Annotator & 2D Sketcher (FreeCAD Style)":
        "PDF 气泡标注 & 2D 草图（FreeCAD 风格）",
    "PDF Bubble Annotator": "PDF 气泡标注",
    "2D Sketcher Workbench": "2D 草图",
    "&File": "文件(&F)",
    "&Open PDF...": "打开 PDF(&O)...",
    "&Export Annotations / JSON...": "导出标注 / JSON(&E)...",
    "E&xit": "退出(&X)",
    "&Help": "帮助(&H)",
    "&About": "关于(&A)",
    "About": "关于",
    "Language": "语言",
    "Model / Tree View": "模型 / 树视图",
    "<b>Elements Tree / Inspector:</b>": "<b>图元树 / 属性面板：</b>",
    "<b>Property View:</b>": "<b>属性视图：</b>",
    "Property": "属性",
    "Value": "值",
    "Python Console & Logs": "Python 控制台与日志",
    "  <b>Workbench: </b> ": "  <b>工作台: </b> ",
    "Open PDF File": "打开 PDF 文件",
    "PDF Files (*.pdf)": "PDF 文件 (*.pdf)",
    (
        "<h3>FreeCAD-Style Modularity Demo</h3>"
        "<p>A dual-workbench architecture:<br>"
        "1. PDF Inspection (FAI ballooning)<br>"
        "2. Parametric 2D Sketcher</p>"
    ): (
        "<h3>FreeCAD 风格模块化演示</h3>"
        "<p>双工作台架构：<br>"
        "1. PDF 检验（FAI 气泡标注）<br>"
        "2. 参数化 2D 草图</p>"
    ),
    "FreeCAD-Style Modularity": "FreeCAD 风格模块化",
    ">>> FreeCAD-Style Environment Initialized.":
        ">>> FreeCAD 风格环境已初始化。",
    ">>> Ready for PDF Inspection & 2D Sketching.":
        ">>> 已就绪：PDF 检验与 2D 草图绘制。",

    # ---- PDF annotator workbench ----
    "Open PDF": "打开 PDF",
    "Export PDF": "导出 PDF",
    "Export PNG": "导出 PNG",
    "Batch PNG": "批量 PNG",
    "Print": "打印",
    "Add Bubble": "添加气泡",
    "Seq": "序号",
    "Size": "大小",
    "Border": "边框",
    "Font": "字号",
    "Outer": "外圈",
    "Fill": "填充",
    "Text": "文字",
    "Transparent": "透明填充",
    "Fit": "适合",
    "Undo": "撤销",
    "Redo": "重做",
    "Clear": "清空",
    "Renumber": "重编号",
    "No drawing opened": "未打开图纸",
    "Tool:": "工具:",
    "Coords:": "坐标:",
    "Select": "选择",
    "Bubble": "气泡",
    "Open Failed": "打开失败",
    "Could not open PDF:": "无法打开 PDF：",
    "Export Failed": "导出失败",
    "Could not write PDF:": "无法写入 PDF：",
    "Could not write PNG:": "无法写入 PNG：",
    "Batch PNG failed:": "批量 PNG 失败：",
    "Could not write file:": "无法写入文件：",
    "Success": "成功",
    "No PDF": "无 PDF",
    "Please open a PDF drawing first.": "请先打开 PDF 图纸。",
    "Export Annotated PDF": "导出标注 PDF",
    "Export Current Page PNG": "导出当前页 PNG",
    "PNG Files (*.png)": "PNG 文件 (*.png)",
    "Choose PNG Output Folder": "选择 PNG 输出目录",
    "Export Balloons JSON": "导出气泡 JSON",
    "JSON Files (*.json)": "JSON 文件 (*.json)",
    "PDF File": "PDF 文件",
    "Page": "页码",
    "Balloons (Total)": "气泡（总数）",
    "Balloons (This Page)": "气泡（本页）",
    "Inspection Standard": "检验标准",
    "Selected Balloon": "当前气泡",
    "Position": "位置",
    "Size / Border / Font": "大小 / 边框 / 字号",
    "Balloon": "气泡",
    "Removed balloon.": "已删除气泡。",
    "Cleared all balloons.": "已清空全部气泡。",
    "Auto-renumbered balloons sequentially per page.":
        "已按页顺序自动重编号气泡。",
    "Undo.": "撤销。",
    "Redo.": "重做。",
    "Sent current page to printer.": "已将当前页发送到打印机。",

    # ---- sketcher workbench ----
    "Line": "直线",
    "Circle": "圆",
    "Arc": "圆弧",
    "Rect": "矩形",
    "Construction": "构造几何",
    "Snap": "捕捉",
    " Grid ": " 网格 ",
    "Coincident": "重合",
    "Parallel": "平行",
    "Perp": "垂直",
    "Equal": "相等",
    "Length": "长度",
    "Radius": "半径",
    "Lock": "锁定",
    "Solve": "求解",
    "Delete": "删除",
    "DOF:": "自由度:",
    "Fully constrained sketch": "草图已完全约束",
    "Conflicting constraints - sketch could not be solved":
        "约束冲突 - 无法求解",
    "Empty sketch": "空草图",
    "Over-constrained (redundant/conflicting)": "约束冲突（冗余/冲突）",
    " (redundant constraints detected)": "（检测到冗余约束）",
    "Solver Status": "求解状态",
    "Degrees of Freedom": "剩余自由度",
    "Lines / Circles / Arcs": "直线 / 圆 / 圆弧",
    "Active Constraints": "活动约束",
    "Solver Engine": "求解引擎",
    "SciPy least-squares": "SciPy 最小二乘",
    "DOF fallback (no SciPy)": "DOF 回退（无 SciPy）",
    "Fully constrained": "完全约束",
    "Conflicting / unsatisfiable": "冲突 / 不可满足",
    "Under-constrained": "欠约束",
    " (construction)": "（构造）",
    "Length Constraint": "长度约束",
    "Length (mm):": "长度 (mm)：",
    "Radius Constraint": "半径约束",
    "Radius (mm):": "半径 (mm)：",
    "Endpoint already coincident.": "端点已重合。",
    "Nothing to lock.": "没有可锁定的图元。",
    "Circle rejected: radius too small.": "圆被拒绝：半径过小。",
    "Arc rejected: the three points are collinear.":
        "圆弧被拒绝：三点共线。",
    "Rectangle rejected: degenerate shape.": "矩形被拒绝：形状退化。",
    "In-progress geometry cancelled.": "已取消进行中的绘制。",
    "Sketch cleared.": "草图已清空。",
    "Export Sketch JSON": "导出草图 JSON",
    "Exported": "导出成功",
}

# Template strings rendered with .format() at use time
TEMPLATES = {
    "Under-constrained sketch with {n} degrees of freedom":
        "欠约束草图，剩余 {n} 个自由度",
    "Select {n} line(s) first (or draw {n}).":
        "请先选择 {n} 条直线（或先绘制）。",
    "Deleted {n} geometry element(s).": "已删除 {n} 个图元。",
    "Construction geometry mode: {v}": "构造几何模式：{v}",
    "Sketcher tool: {v}": "草图工具：{v}",

    # ---- sketcher (FreeCAD parity tools/constraints) ----
    "Point": "点",
    "Polyline": "折线",
    "Reference line": "参考线",
    "Reference line rejected: zero length.": "参考线被拒绝：长度为零。",
    "Reference line added from ({x1}, {y1}) to ({x2}, {y2}).":
        "参考线已添加，自 ({x1}, {y1}) 至 ({x2}, {y2})。",
    "Line Length": "直线长度",
    "Length (mm):": "长度 (mm)：",
    "Radius": "半径",
    "Radius (mm):": "半径 (mm)：",
    "Rectangle Width": "矩形宽度",
    "Width (mm):": "宽度 (mm)：",
    "Rectangle Height": "矩形高度",
    "Height (mm):": "高度 (mm)：",
    "Selected {n} element(s).": "已选中 {n} 个图元。",
    "Conflicting Constraint": "约束冲突",
    "This value conflicts with the existing constraints and "
    "was not applied. Remove or change the conflicting "
    "constraint first.":
        "该数值与现有约束冲突，未生效。请先移除或修改冲突的约束。",
    "Rectangle size conflicts with existing constraints.":
        "矩形尺寸与现有约束冲突。",
    "Arc (3 pts)": "三点圆弧",
    "Rectangle": "矩形",
    "Triangle": "三角形",
    "Square": "正方形",
    "Point-on": "点在对象上",
    "Tangent": "相切",
    "Symmetric": "对称",
    "Distance": "距离",
    "Dist X": "水平距离",
    "Dist Y": "垂直距离",
    "Diameter": "直径",
    "Angle": "角度",
    "Block": "块",
    "Undo": "撤销",
    "Redo": "重做",
    "toggles selection": "切换选中项",
    "Value (mm):": "数值 (mm)：",
    "Value:": "数值：",
    "Distance Constraint": "距离约束",
    "Horizontal Distance Constraint": "水平距离约束",
    "Vertical Distance Constraint": "垂直距离约束",
    "Diameter Constraint": "直径约束",
    "Angle Constraint": "角度约束",
    "Angle (deg):": "角度 (度)：",
    "Edit Constraint": "编辑约束",
    "POINT_ON constraint added.": "已添加点在对象上约束。",
    "SYMMETRIC constraint added.": "已添加对称约束。",
    "SYMMETRIC constraint added ({n} pairs).": "已添加对称约束（{n} 对）。",
    "Symmetric needs two DIFFERENT points (e.g. two "
    "corners). For a single line, mirror its endpoints "
    "about the axis instead.":
        "对称需要两个不同的点（如矩形的两个角点）。镜像整条线请用轴对称工具。",
    "{c} constraint added.": "已添加 {c} 约束。",
    "{c} = {v} constraint added.": "已添加 {c} = {v} 约束。",
    "ANGLE = {v} deg constraint added.": "已添加角度 = {v}° 约束。",
    "{c} constraint added (geometry fixed in place).":
        "已添加 {c} 约束（几何已固定）。",
    "{c} changed to {v}.": "{c} 已改为 {v}。",
    "{c} constraint removed.": "已删除 {c} 约束。",
    "Nothing to undo.": "没有可撤销的操作。",
    "Nothing to redo.": "没有可重做的操作。",
    "Constraint picking cancelled.": "已取消约束拾取。",
    "Nothing picked - click closer to the target.":
        "未拾取到对象 - 请更靠近目标点击。",
    "Pick: {what}": "拾取：{what}",
    "Select {what} for the {c} constraint": "为 {c} 约束选择：{what}",
    "Select geometry to toggle construction.": "请先选择要切换构造属性的图元。",
    "Toggled construction flag on {n} element(s).":
        "已切换 {n} 个图元的构造属性。",
    "Auto-constraint: horizontal": "自动约束：水平",
    "Auto-constraint: vertical": "自动约束：垂直",
    "Rectangle created with automatic H/V constraints.":
        "矩形已创建（自动添加水平/垂直约束）。",
    "Polygon ({n} sides) created with equal-side constraints.":
        "多边形（{n} 边）已创建（自动添加等边约束）。",
    "Polygon rejected: radius too small.": "多边形被拒绝：半径过小。",
    "Line rejected: zero length.": "直线被拒绝：长度为零。",
    "Point added at ({x}, {y}).": "已添加点 ({x}, {y})。",
    "COINCIDENT: points merged at ({x}, {y}).": "重合：点已合并于 ({x}, {y})。",
    "Arc rejected: radius too small.": "圆弧被拒绝：半径过小。",
    "point": "点",
    "line": "直线",
    "circle/arc": "圆/圆弧",
    "curve": "曲线",
    "geometry": "几何",
    "line or center point": "直线或中心点",
    "curve or point": "曲线或点",
    "second point": "第二个点",
    "Points / Lines / Circles / Arcs": "点 / 直线 / 圆 / 圆弧",
    "Dimension constraints": "尺寸标注",
    "Dimension": "尺寸标注",
    "Horizontal distance constraint": "水平距离约束",
    "Vertical distance constraint": "限制垂直距离",
    "Distance constraint": "距离约束",
    "Radius constraint": "半径约束",
    "Diameter constraint": "约束直径",
    "Angle constraint": "角度约束",
    "Lock constraint": "锁定约束",
    "2D CAD": "2D CAD",
    "Nominal:": "名义值：",
    "+Tol:": "上公差：",
    "-Tol:": "下公差：",
    "Decimals:": "小数位：",
    "Insert TechDraw page template": "插入 TechDraw 图纸模板",
    "TechDraw template {n} inserted.": "已插入 TechDraw 模板 {n}。",
    "&New 2D Sketch": "新建 2D 草图(&N)",
    "&Open 2D Sketch...": "打开 2D 草图(&O)...",
    "Open 2D Sketch": "打开 2D 草图",
    "&Import 2D CAD (DXF)...": "导入 2D CAD (DXF/DWG)(&I)...",
    "Import 2D CAD (DXF)": "导入 2D CAD (DXF)",
    "Import 2D CAD": "导入 2D CAD",
    "CAD Files (*.dxf *.dwg);;DXF Files (*.dxf);;DWG Files (*.dwg)":
        "CAD 文件 (*.dxf *.dwg);;DXF 文件 (*.dxf);;DWG 文件 (*.dwg)",
    "DWG support requires the 'ezdwg' package (pip install ezdwg).":
        "DWG 支持需要安装 'ezdwg' 包（pip install ezdwg）。",
    "&Save 2D Sketch (JSON)...": "保存 2D 草图 (JSON)(&S)...",
    "Save 2D Sketch (JSON)": "保存 2D 草图 (JSON)",
    "Sketch Files (*.sketch.json);;JSON Files (*.json)":
        "草图文件 (*.sketch.json);;JSON 文件 (*.json)",
    "Open Failed": "打开失败",
    "Import Failed": "导入失败",
    "No supported entities (LINE/CIRCLE/ARC/POINT) found.":
        "未找到支持的实体（LINE/CIRCLE/ARC/POINT）。",
    "Opened 2D sketch {v}": "已打开 2D 草图 {v}",
    "2D sketch saved to {v}": "2D 草图已保存至 {v}",
    "Imported {n} entities from {v}": "已从 {v} 导入 {n} 个实体",
    "New 2D sketch created.": "已新建 2D 草图。",
    "Save as 2D CAD (DXF)...": "另存为 2D CAD (DXF)...",
    "Save as 2D Vector (SVG)...": "另存为 2D 矢量 (SVG)...",
    "Save as 2D Vector (SVG)": "另存为 2D 矢量 (SVG)",
    "SVG Files (*.svg)": "SVG 文件 (*.svg)",
    "Export SVG": "导出 SVG",
    "2D vector (SVG) saved to {v}": "2D 矢量 (SVG) 已保存至 {v}",
    "Save as 2D CAD (DXF)": "另存为 2D CAD (DXF)",
    "DXF Files (*.dxf)": "DXF 文件 (*.dxf)",
    "Export 2D CAD": "导出 2D CAD",
    "The sketch is empty.": "草图为空。",
    "2D CAD (DXF) saved to {v}": "2D CAD (DXF) 已保存至 {v}",
}


def set_language(lang):
    global _LANG
    _LANG = lang


def language():
    return _LANG


def available_languages():
    return (("en", "English"), ("zh_CN", "简体中文"))


def _zh_of(key):
    if key in TRANSLATIONS:
        return TRANSLATIONS[key]
    return TEMPLATES.get(key)


def tr(source):
    if _LANG == "zh_CN":
        zh = _zh_of(source)
        if zh is not None:
            return zh
    return source


def trt(source, **kwargs):
    """Translate a template containing {placeholders} and format it."""
    template = tr(source)
    return template.format(**kwargs)
