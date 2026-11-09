"""Native FluentPy asset selector shared by gunsmith and inspection."""
import os
from fluentpy import widgets as W
from PySide6.QtWidgets import QLabel, QTableWidgetItem, QAbstractItemView, QHeaderView


def asset_picker(title, rows, prefer="", parent=None):
    dialog = W.FramelessDialog(title, parent=parent)
    dialog.setMinimumWidth(800)
    dialog.chosen = ""
    search = W.LineEdit(placeholder="搜索中文名、文件名或路径", parent=dialog)
    table = W.TableWidget(dialog)
    table.setColumnCount(2)
    table.setHorizontalHeaderLabels(["名称", "资源路径"])
    table.setSelectionBehavior(QAbstractItemView.SelectRows)
    table.setSelectionMode(QAbstractItemView.SingleSelection)
    table.setEditTriggers(QAbstractItemView.NoEditTriggers)
    table.setMinimumHeight(380)
    table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
    table.horizontalHeader().setStretchLastSection(True)
    hint = QLabel(dialog)
    for widget in (search, table, hint): dialog.add_content_widget(widget)
    source = list(rows)
    shown = []

    def refresh():
        text = search.text().strip().casefold()
        hits = [r for r in source if not text or text in " ".join(str(v or "") for v in r).casefold()]
        hits.sort(key=lambda r: (0 if prefer and prefer.casefold() in str(r).casefold() else 1,
                                 0 if r[1] else 1, 0 if "_3p." in r[0].lower() else 1, len(r[0])))
        shown[:] = hits[:500]
        table.setRowCount(len(shown))
        for i, row in enumerate(shown):
            for j, value in enumerate((row[1] or os.path.basename(row[0]), row[0])):
                item = QTableWidgetItem(value)
                item.setToolTip(row[0])
                table.setItem(i, j, item)
        hint.setText(f"共 {len(source)} 个资源，匹配 {len(hits)} 个" + ("，请搜索缩小范围（显示前 500 个）" if len(hits)>500 else ""))
        if shown: table.selectRow(0)

    def accept():
        i = table.currentRow()
        if 0 <= i < len(shown):
            dialog.chosen = shown[i][0]
            dialog.accept()

    dialog.yes_button.clicked.disconnect()
    dialog.yes_button.clicked.connect(accept)
    dialog.setYesButtonText("选择")
    search.textChanged.connect(refresh)
    table.cellDoubleClicked.connect(lambda *_: accept())
    refresh()
    dialog.search = search
    dialog.table = table
    return dialog
