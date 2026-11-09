"""Dedicated real skeletal animation viewer; never substitutes a camera orbit."""
from copy import deepcopy
import os
import threading
import time

from fluentpy import widgets as W
from PySide6.QtCore import Qt, QThread, QTimer, Signal
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QSplitter, QTableWidgetItem, QAbstractItemView, QHeaderView

from app.asset_picker import asset_picker
from app.viewer import create_viewport
from core import loader
from core.inspection import related_models, decode_animation, SkinPlayer
from core.inspection_catalog import playable_animations, inspectable_paths, inspection_catalog
from core.inspection_scene import InspectionScene, load_companion


class _ExportWorker(QThread):
    ready = Signal(object,str)

    def __init__(self,bundle,clip,path,hands=None,track=None,parent=None):
        super().__init__(parent)
        self.args=(bundle,clip,path)
        self.hands,self.track=hands,track

    def run(self):
        try:
            from exporters.animation_glb import export_animation
            result=export_animation(*self.args,hands=self.hands,track=self.track)
            self.ready.emit(result,'')
        except Exception as exc:self.ready.emit(None,str(exc))


class _Worker(QThread):
    ready = Signal(object, str)
    progress = Signal(int, int)

    def __init__(self, path, model=False, parent=None, bundle=None, model_path="", candidates=None,record=None):
        super().__init__(parent)
        self.path, self.model = path, model
        self.cancel = threading.Event()
        self.bundle, self.model_path = bundle, model_path
        self.candidates = list(candidates or [path])
        self.record=record

    def run(self):
        try:
            if self.model:
                result = loader.load_model(self.path)
            elif self.record is not None:
                result=load_companion(self.record,self.model_path,inspection_catalog(),self.cancel)
            else:
                def compatible(bundle, clips):
                    if bundle is None: return []
                    accepted=[]
                    for clip in clips:
                        try:
                            SkinPlayer(bundle.mesh, clip)
                            if clip.duration>0: accepted.append(clip)
                        except (ValueError, AttributeError, IndexError):
                            pass
                    return accepted
                index=inspection_catalog()
                alternatives,full_bundles={},{}
                verified=[]
                last_error=""
                for number,animation in enumerate(self.candidates,1):
                    if self.cancel.is_set(): return
                    self.progress.emit(number,len(self.candidates))
                    try:
                        clips = decode_animation(animation, self.cancel)
                        if self.cancel.is_set(): return
                        chosen, chosen_path = None, self.model_path
                        accepted=compatible(self.bundle, clips)
                        if not accepted and getattr(self.bundle,'inspection_assembly',False):continue
                        if not accepted:
                            paths = related_models(self.model_path)
                            paths.sort(key=lambda p: (0 if '_1p' in p.casefold() else 1, len(p)))
                            anim_meta=index.metadata(animation)
                            for candidate in paths[:24]:
                                if self.cancel.is_set(): return
                                candidate_meta=index.metadata(candidate)
                                if not anim_meta or not candidate_meta or anim_meta['skeleton']!=candidate_meta['skeleton']:continue
                                try:
                                    if candidate not in alternatives:
                                        alternatives[candidate]=loader.load_model(candidate,want_textures=False)
                                    accepted=compatible(alternatives[candidate],clips)
                                    if accepted:
                                        if candidate not in full_bundles:full_bundles[candidate]=loader.load_model(candidate)
                                        chosen,chosen_path=full_bundles[candidate],candidate
                                        break
                                except (ValueError,OSError,KeyError,AttributeError):
                                    continue
                        if accepted:
                            verified.append(dict(clips=accepted,bundle=chosen,path=chosen_path,animation=animation))
                    except InterruptedError:
                        return
                    except Exception as exc:                   # noqa: BLE001
                        # 无效动作、加算动作、骨骼对不上都不该进列表；但要把原因留下，
                        # 否则解码组件起不来时页面只会说「没有可播放的动作」，查不出所以然。
                        if not last_error:
                            last_error = f"{type(exc).__name__}: {exc}".strip()[:600]
                        continue
                if verified:
                    verified[0]=load_companion(verified[0],self.model_path,index,self.cancel)
                result=(dict(verified[0],playable=verified) if verified
                        else dict(playable=[],error_hint=last_error))
            if not self.cancel.is_set(): self.ready.emit(result, "")
        except Exception as exc:
            if not self.cancel.is_set(): self.ready.emit(None,str(exc))


class InspectionPage(QWidget):
    availabilityChanged = Signal(str,int)
    def __init__(self, window=None, parent=None,*,compact=False):
        super().__init__(parent)
        self.setObjectName("inspectionPage")
        self.host_window = window
        self.compact=compact
        self.bundle = self.player = self._worker = None
        self._record = None
        self._export_worker = None
        self.vpath = ""
        self.selection_vpath = ""
        self._source_bundle = None
        self._playable = {}
        self._verified = False
        self._generation = 0
        self._pending = None
        self._auto_pending = False
        self._preview_pending = False
        self._closing = False
        self.clips = []
        self.seconds = 0.0
        self._playing = False
        self._tick_time = time.monotonic()
        self._timer = QTimer(self)
        self._timer.setInterval(33)
        self._timer.timeout.connect(self._tick)
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)
        top = QHBoxLayout()
        self.use_button = W.Button("在模型库选择模型", self)
        self.model_button = W.Button("选择模型", self)
        self.any_button = W.Button("重新查找当前模型动画", self)
        self.cancel_button = W.Button("取消加载", self)
        self.cancel_button.setEnabled(False)
        for button in (self.use_button, self.model_button, self.any_button, self.cancel_button): top.addWidget(button)
        self.action_picker=W.ComboBox(self)
        self.action_picker.setVisible(compact)
        self.action_picker.setMinimumWidth(120)
        top.insertWidget(0,self.action_picker,1)
        if compact:
            for button in (self.use_button,self.model_button,self.any_button):button.hide()
        top.addStretch()
        root.addLayout(top)
        self.model_label = QLabel("自动跟随当前选中的模型，展示该模型对应的检视动画。", self)
        self.model_label.setWordWrap(True)
        root.addWidget(self.model_label)
        split = QSplitter(Qt.Horizontal, self)
        left = QWidget(split)
        self.actions_panel=left
        layout = QVBoxLayout(left)
        layout.setContentsMargins(0, 0, 8, 0)
        self.search = W.LineEdit(placeholder="搜索动作名称，例如 Inspect、Open、Loop", parent=left)
        self.table = W.TableWidget(left)
        self.table.setColumnCount(2)
        self.table.setHorizontalHeaderLabels(["当前模型的动作", "文件夹"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.load_button = W.AccentButton("加载选中动作", left)
        layout.addWidget(self.search)
        layout.addWidget(self.table, 1)
        layout.addWidget(self.load_button)
        split.addWidget(left)
        self.viewport = create_viewport(self)
        split.addWidget(self.viewport)
        split.setSizes([340, 900])
        if compact:left.hide()
        root.addWidget(split, 1)
        controls = QHBoxLayout()
        self.play_button = W.AccentButton("播放", self)
        self.reset_button = W.Button("回到开头", self)
        self.timeline = W.Slider(Qt.Horizontal, self)
        self.timeline.setRange(0, 10000)
        self.time_label = QLabel("0.00 / 0.00 秒", self)
        self.speed = W.ComboBox(self)
        for speed in (.25,.5,1,1.5,2): self.speed.addItem(f"{speed:g}×", speed)
        self.speed.setCurrentIndex(2)
        self.loop = W.CheckBox("循环播放", self)
        self.loop.setChecked(True)
        self.segment = W.ComboBox(self)
        self.segment.setMinimumWidth(180)
        for widget in (self.play_button,self.reset_button,self.timeline,self.time_label):
            controls.addWidget(widget, 1 if widget is self.timeline else 0)
        root.addLayout(controls)
        options=QHBoxLayout()
        self.view_mode=W.ComboBox(self)
        self.view_mode.addItems(['第一人称','自由观察'])
        self.view_mode.setToolTip('第一人称跟随游戏相机挂点；自由观察可旋转、缩放。')
        for widget in (self.view_mode,self.speed,self.loop,self.segment):options.addWidget(widget,1 if widget is self.segment else 0)
        root.addLayout(options)
        export_controls=QHBoxLayout()
        self.show_hands=W.CheckBox("角色手臂（播放 / 导出）",self)
        self.show_hands.setChecked(True)
        self.show_hands.setToolTip("自动匹配游戏原有的第一人称手臂动作，并让物品跟随手部挂点。")
        self.export_button=W.AccentButton("导出当前动画 · GLB",self)
        self.export_button.setToolTip("导出当前动作片段，包含模型、骨骼、权重、贴图和动画，可导入 Blender。")
        export_controls.addWidget(self.show_hands);export_controls.addStretch();export_controls.addWidget(self.export_button)
        root.addLayout(export_controls)
        self.export_notice=W.InfoBar("动画导出","",self,tone="info",orientation="vertical",closable=True)
        self.export_notice.hide();root.addWidget(self.export_notice)
        self.status = QLabel("选择模型后自动展示它的检视动作，切换模型后动作也会随之更新。", self)
        self.status.setWordWrap(True)
        root.addWidget(self.status)
        self.use_button.clicked.connect(self._use_current)
        self.model_button.clicked.connect(self._pick_model)
        self.any_button.clicked.connect(self._pick_animation)
        self.cancel_button.clicked.connect(self._cancel)
        self.load_button.clicked.connect(self._load_selected)
        self.table.cellClicked.connect(lambda *_: self._load_selected())
        self.search.textChanged.connect(self._filter)
        self.play_button.clicked.connect(self._toggle)
        self.reset_button.clicked.connect(lambda: self._seek(0))
        self.timeline.valueChanged.connect(self._scrub)
        self.segment.currentIndexChanged.connect(self._activate_clip)
        self.show_hands.toggled.connect(lambda *_:self._activate_clip(self.segment.currentIndex()))
        self.export_button.clicked.connect(self._export_animation)
        self.view_mode.currentIndexChanged.connect(self._change_view)
        self.action_picker.currentIndexChanged.connect(self._pick_compact_action)
        self._rows = self._shown = []
        self._set_play_enabled(False)

    def _set_play_enabled(self, enabled):
        for widget in (self.play_button,self.reset_button,self.timeline,self.speed,self.loop): widget.setEnabled(enabled)
        self.segment.setEnabled(bool(self.clips))
        self.export_button.setEnabled(enabled and self._export_worker is None and self._worker is None)

    def _use_current(self):
        if self.host_window is not None:
            self.host_window.switchTo(self.host_window.library_page)
        else:
            self._pick_model()

    def begin_selection(self, vpath):
        """Invalidate every callback from the previously selected model immediately."""
        self._generation += 1
        self._pending = None
        self._auto_pending = False
        self._preview_pending = False
        if self._worker is not None: self._worker.cancel.set()
        self._pause()
        self.player = self.bundle = self._source_bundle = None
        self._record=None
        self.selection_vpath = self.vpath = vpath
        self.clips = []
        self._playable = {}
        self._verified = False
        self._rows = self._shown = []
        self.search.blockSignals(True)
        self.search.clear()
        self.search.blockSignals(False)
        self.table.setRowCount(0)
        self.action_picker.blockSignals(True);self.action_picker.clear();self.action_picker.blockSignals(False)
        self.segment.blockSignals(True)
        self.segment.clear()
        self.segment.blockSignals(False)
        self.timeline.blockSignals(True)
        self.timeline.setValue(0)
        self.timeline.blockSignals(False)
        self.seconds = 0.0
        self.time_label.setText("0.00 / 0.00 秒")
        self._set_play_enabled(False)
        self.viewport.set_mesh(None, [], [])
        self.model_label.setText("模型："+os.path.basename(vpath))
        self.status.setText("正在加载当前选中的模型…")
        self.export_notice.hide()
        self._update_load_controls()

    def selection_error(self, vpath, error):
        if vpath == self.selection_vpath:
            self.status.setText("当前模型加载失败："+str(error).splitlines()[0])

    def set_bundle(self, bundle, vpath, *, autoplay=True):
        self.begin_selection(vpath)
        self._source_bundle = bundle
        self.model_label.setText("当前模型："+(bundle.display_name_cn or bundle.display_name or os.path.basename(vpath)))
        self._rows = playable_animations(vpath)
        if self.compact:
            actions=[r for r in self._rows if any(k in r[1].casefold() for k in ('inspect','check','show'))]
            if actions:self._rows=actions
        self._filter()
        self._preview_pending = True
        self._auto_pending = autoplay and bool(self._rows)
        self.status.setText(f"当前模型有 {len(self._rows)} 个对应动作，打开检视页后自动播放。" if self._rows else
                            "当前模型未找到对应的检视动画。")
        self._update_load_controls()
        if self.isVisible(): self._present_selection()

    def _present_selection(self):
        if self._preview_pending and self._source_bundle is not None:
            self._preview_pending = False
            self._show_bundle(self._source_bundle, self.selection_vpath)
        if self._auto_pending and self._source_bundle is not None:
            self._auto_pending = False
            paths = [row[0] for row in self._rows]
            if paths: self._start(paths[0], candidates=paths)

    def _show_bundle(self, bundle, vpath):
        # Only the mesh deforms; texture pixels are immutable and can be shared.
        from copy import copy
        self.bundle = copy(bundle)
        self.bundle.mesh = deepcopy(bundle.mesh)
        self.vpath = vpath
        self.viewport.set_mesh(self.bundle.mesh,self.bundle.materials,self.bundle.textures)

    def showEvent(self, event):
        super().showEvent(event)
        self._present_selection()

    def hideEvent(self, event):
        self._pause()
        super().hideEvent(event)

    def _update_load_controls(self):
        busy = self._worker is not None
        self.model_button.setEnabled(not self._closing)
        self.use_button.setEnabled(not self._closing)
        self.any_button.setEnabled(self._source_bundle is not None and not busy)
        self.load_button.setEnabled(bool(self._rows) and not busy)
        self.cancel_button.setEnabled(busy)
        self.export_button.setEnabled(self.player is not None and not busy and self._export_worker is None)

    def _filter(self):
        text=self.search.text().casefold().strip()
        self._shown=[r for r in self._rows if self._verified and (not text or text in r[0].casefold())]
        self.table.setRowCount(len(self._shown))
        for i,row in enumerate(self._shown):
            item=QTableWidgetItem(row[1])
            item.setToolTip(row[0])
            self.table.setItem(i,0,item)
            self.table.setItem(i,1,QTableWidgetItem(row[0].rsplit('/',2)[-2]))
        if self._shown: self.table.selectRow(0)
        self.action_picker.blockSignals(True)
        self.action_picker.clear()
        for row in self._shown:self.action_picker.addItem(row[1])
        self.action_picker.blockSignals(False)

    def _pick_compact_action(self,index):
        if 0<=index<len(self._shown):
            self.table.selectRow(index);self._load_selected()

    def _pick_model(self):
        browser=getattr(self.host_window,'browser',None)
        if browser is not None and not browser.is_ready:
            self.status.setText("正在筛选可检视模型，请等待模型库索引完成。")
            return
        eligible=browser._inspectable_paths if browser is not None else inspectable_paths()
        rows=[(p,os.path.basename(p),"","","") for p in sorted(eligible)]
        dialog=asset_picker("选择可检视的模型",rows,parent=self)
        if not dialog.exec() or not dialog.chosen: return
        if self.host_window is not None:
            self.host_window.load_vpath(dialog.chosen)
        else:
            self.begin_selection(dialog.chosen)
            self._start(dialog.chosen, True)

    def _pick_animation(self):
        # Refresh only this selected model. There is no global animation picker.
        if self._source_bundle is not None:
            self.set_bundle(self._source_bundle, self.selection_vpath)

    def _load_selected(self):
        i=self.table.currentRow()
        if self._source_bundle is not None and 0<=i<len(self._shown):
            self._auto_pending = False
            record=self._playable.get(self._shown[i][0])
            if record is not None and record.get('hands_checked'):
                self._pending=None
                if self._worker:self._worker.cancel.set()
                self._ready(record,"",self._shown[i][0],False)
            elif record is not None:self._start(self._shown[i][0],record=record)
            else: self._start(self._shown[i][0])

    def _start(self, path, model=False, *, candidates=None,record=None):
        if self._closing: return
        request = (self._generation, path, model, list(candidates or [path]),record)
        if self._worker is not None:
            self._worker.cancel.set()
            self._pending = request
            return
        self._launch(request)

    def _launch(self, request):
        generation,path,model,candidates,record = request
        if generation != self._generation or self._closing: return
        self._pause()
        self.status.setText("正在加载模型…" if model else "正在加载当前模型对应的检视动画…")
        worker=_Worker(path,model,self,bundle=self._source_bundle,
                       model_path=self.selection_vpath,candidates=candidates,record=record)
        self._worker=worker
        self._update_load_controls()
        worker.ready.connect(lambda result,error: self._worker_ready(worker,generation,result,error,path,model))
        if hasattr(worker,'progress'):
            worker.progress.connect(lambda i,n: self.status.setText(f"正在核对当前模型的可播放动作 {i}/{n}…")
                                    if worker is self._worker and generation == self._generation
                                    and not self._closing and not worker.cancel.is_set() else None)
        worker.finished.connect(lambda: self._finished(worker))
        worker.start()

    def _worker_ready(self, worker, generation, result, error, path, model):
        if self._closing or worker is not self._worker or generation != self._generation or worker.cancel.is_set(): return
        self._ready(result,error,path,model)

    def _finished(self, worker):
        if worker is self._worker: self._worker=None
        worker.deleteLater()
        self._update_load_controls()
        pending,self._pending = self._pending,None
        if pending is not None and pending[0] == self._generation and not self._closing:
            self._launch(pending)

    def _ready(self,result,error,path,model):
        if error:
            self.status.setText(error)
            return
        if model:
            self.set_bundle(result,path)
            return
        if 'playable' in result:
            self._verified=True
            self._playable={r['animation']:r for r in result['playable']}
            self._rows=[r for r in self._rows if r[0] in self._playable]
            self._filter()
            self._update_load_controls()
            self.availabilityChanged.emit(self.selection_vpath,len(self._rows))
            if not self._playable:
                hint = result.get('error_hint') or ""
                self.status.setText("当前模型没有可独立播放的检视动作。" +
                                    (f"（{hint}）" if hint else ""))
                self._set_play_enabled(False)
                return
        self._pause()
        self.player=None
        self._record=result
        if result.get('animation') in self._playable:self._playable[result['animation']]=result
        self._show_bundle(result['bundle'] or self._source_bundle,result['path'])
        self.clips=result['clips']
        animation=result.get('animation',path)
        for i,row in enumerate(self._shown):
            if row[0] == animation:
                self.table.selectRow(i)
                self.action_picker.blockSignals(True);self.action_picker.setCurrentIndex(i);self.action_picker.blockSignals(False)
                break
        self.segment.blockSignals(True)
        self.segment.clear()
        for clip in self.clips: self.segment.addItem(clip.name)
        self.segment.blockSignals(False)
        selected=0
        for i,clip in enumerate(self.clips):
            try:
                SkinPlayer(self.bundle.mesh,clip)
                selected=i
                break
            except (ValueError, AttributeError, IndexError):
                pass
        self.segment.blockSignals(True)
        self.segment.setCurrentIndex(selected)
        self.segment.blockSignals(False)
        self._activate_clip(selected)

    def _activate_clip(self,index):
        self._pause()
        if not (0<=index<len(self.clips)) or self.bundle is None: return
        try:
            record=self._record or {}
            source=record.get('bundle') or self._source_bundle
            hands=record.get('hands')
            track=hands['tracks'][index] if hands and index<len(hands['tracks']) else None
            active=self.show_hands.isChecked() and track is not None
            self.player=InspectionScene(source,self.clips[index],hands['bundle'] if track else None,track,show_hands=active)
            self.bundle=self.player.bundle
            display=self.player.display
            self.viewport.set_mesh(display.mesh,display.materials,display.textures)
            self._set_play_enabled(True)
            self.viewport.frame_all()
            self._seek(0)
            note=' · 角色手臂同步播放' if active else (' · '+record.get('hands_note','当前片段没有配套手臂') if self.show_hands.isChecked() else ' · 仅物品')
            self.status.setText(f"{self.clips[index].name} · {len(self.clips[index].poses)} 帧 · {self.clips[index].fps:.1f} FPS"+note)
            self._toggle()
        except Exception as exc:
            self.player=None
            self._set_play_enabled(False)
            self.viewport.update_geometry()
            self.status.setText(str(exc))

    def _change_view(self,*_):
        if self.player is None:return
        self.viewport.frame_all()
        self._apply_camera()

    def _apply_camera(self):
        pose=self.player.camera_pose() if self.player is not None and self.view_mode.currentIndex()==0 else None
        self.viewport.set_first_person(pose)

    def _export_animation(self):
        if self.player is None or self._export_worker is not None or self._worker is not None:return
        from PySide6.QtWidgets import QFileDialog
        import re
        name=re.sub(r'[<>:"/\\|?*]','_',self.player.clip.name)+'.glb'
        path,_=QFileDialog.getSaveFileName(self,"导出当前检视动画",name,"骨骼动画 GLB (*.glb)")
        if not path:return
        if not path.casefold().endswith('.glb'):path+='.glb'
        self._pause()
        worker=_ExportWorker(self.player.source,self.player.clip,path,
                             self.player.hands_source,self.player.track if self.player.body is not None else None,self)
        self._export_worker=worker
        self.export_button.setEnabled(False)
        self.export_notice.set_detail('正在导出模型、骨骼、贴图和当前动画…');self.export_notice.show()
        worker.ready.connect(self._export_ready)
        worker.finished.connect(lambda:self._export_finished(worker))
        worker.start()

    def _export_ready(self,result,error):
        if self._closing:return
        self.export_notice.set_detail('导出失败：'+error if error else
                                     f"导出成功 · {result['frames']} 帧 · "+('包含角色手臂\n' if result['actors']==2 else '仅物品\n')+result['path'])
        self.export_notice.show()

    def _export_finished(self,worker):
        if worker is self._export_worker:self._export_worker=None
        worker.deleteLater()
        self._update_load_controls()

    def _pause(self):
        self._playing=False
        self._timer.stop()
        self.play_button.setText("播放")

    def _toggle(self):
        if self.player is None: return
        if self._playing: self._pause()
        else:
            if self.seconds>=self.player.clip.duration: self._seek(0)
            self._playing=True
            self._tick_time=time.monotonic()
            self.play_button.setText("暂停")
            self._timer.start()

    def _tick(self):
        if not self.isVisible():
            self._pause()
            return
        now=time.monotonic()
        seconds=self.seconds+(now-self._tick_time)*self.speed.currentData()
        self._tick_time=now
        duration=self.player.clip.duration
        if seconds>duration:
            if self.loop.isChecked() and duration>0: seconds%=duration
            else: seconds=duration; self._pause()
        self._seek(seconds)

    def _scrub(self,value):
        if self.player is not None:
            self._seek(value/10000*self.player.clip.duration)
            self._tick_time=time.monotonic()

    def _seek(self,seconds):
        if self.player is None: return
        self.seconds=seconds
        self.player.sample(seconds)
        self._apply_camera()
        self.viewport.update_geometry()
        duration=self.player.clip.duration
        self.timeline.blockSignals(True)
        self.timeline.setValue(round(seconds/max(duration,1e-9)*10000))
        self.timeline.blockSignals(False)
        self.time_label.setText(f"{seconds:.2f} / {duration:.2f} 秒")

    def _cancel(self):
        self._pending = None
        self._auto_pending = False
        if self._worker: self._worker.cancel.set()
        self.status.setText("已取消动画加载。")

    def shutdown(self):
        self._closing = True
        self._pending = None
        self._pause()
        if self._worker:
            self._worker.cancel.set()
            self._worker.wait()
        if self._export_worker:self._export_worker.wait()
