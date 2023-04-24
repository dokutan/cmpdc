#!/usr/bin/env python3

import asyncio
import functools
import sys
import os
import re
import glob
import logging

from PyQt6.QtGui import *
from PyQt6.QtWidgets import *
from PyQt6.QtCore import *

from mpd.asyncio import MPDClient

from desktop_notifier import DesktopNotifier

import mutagen

import qasync
from qasync import asyncSlot, asyncClose, QApplication

# config
mpd_host = "localhost"
mpd_port = 6600
mpd_passwd = ""
music_directory = os.getenv("HOME") + "/Music"
theme = "Adwaita-Dark"
desktop_notification = True

logging.basicConfig(
    format="%(asctime)s %(levelname)s [%(filename)s:%(lineno)d] %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
    level=logging.INFO
)

# disable QImage allocation limit
os.environ['QT_IMAGEIO_MAXALLOC'] = "0"

def format_duration(duration):
    """Formats a duration"""
    h = duration // 3600
    duration = duration % 3600
    m = duration // 60
    s = duration % 60
    if h > 0:
        return "{:d}:{:02d}:{:02d}".format(h, m, s)
    else:
        return "{:02d}:{:02d}".format(m, s)


def format_song(song):
    """Formats a song for the queue, search results, …"""
    return "%s\t%s\n\t%s  •  %s  •  %s" % (
        (song["track"] if "track" in song else "—"),
        (song["title"] if "title" in song else (
            song["file"] if "file" in song else "—"
        )),
        (song["artist"] if "artist" in song else "—"),
        (song["album"] if "album" in song else "—"),
        (format_duration(int(float(song["duration"])))
         if "duration" in song else "—")
    )


def albumart_file_or_none(dir):
    """Looks for an image to be used as albumart in dir"""
    try:
        files = \
            glob.glob(dir + "/*.[Pp][Nn][Gg]") + \
            glob.glob(dir + "/*.[Jj][Pp][Gg]") + \
            glob.glob(dir + "/*.[Jj][Pp][Ee][Gg]")

        with open(files[0], "rb") as albumart:
            return albumart.read()
    except:
        return None


class MPDClient2(MPDClient):
    def __init__(self):
        super().__init__()

    @asyncSlot()
    async def toggle(self):
        """Toggle between stopped/paused and playing"""
        status = await self.status()
        if status["state"] == "play":
            self.pause(1)
        else:
            self.play()

    @asyncSlot()
    async def albumart_or_none(self, currentsong=None):
        """Returns the albumart of the current song or None"""
        try:
            if currentsong is None:
                currentsong = await self.currentsong()
            albumart = await self.albumart(currentsong["file"])
            return albumart["binary"]
        except:
            return None

    @asyncSlot()
    async def readpicture_or_none(self, currentsong=None):
        """Returns the albumart of the current song or None"""
        try:
            if currentsong is None:
                currentsong = await self.currentsong()
            albumart = await self.readpicture(currentsong["file"])
            return albumart["binary"]
        except:
            return None

    @asyncSlot()
    async def rm_save(self, name):
        """Saves the queue as a playlist, even if the playlist exists"""
        try:
            self.rm(name)
        except:
            pass
        finally:
            self.save(name)


class CoverWidget(QWidget):
    """A custom widget to display an album cover"""

    def __init__(self):
        super().__init__()
        self.pixmap = None

    def setPixmap(self, pixmap):
        self.pixmap = pixmap

    def paintEvent(self, event):
        if self.pixmap is not None:
            x = 0
            y = 0

            pixmap = self.pixmap.scaled(event.rect().size(),
                                        Qt.AspectRatioMode.KeepAspectRatio,
                                        Qt.TransformationMode.SmoothTransformation
                                        )

            if self.width() > pixmap.width():
                x = int((self.width() - pixmap.width()) / 2)
            if self.height() > pixmap.height():
                y = int((self.height() - pixmap.height()) / 2)

            painter = QPainter(self)
            painter.drawPixmap(x, y, pixmap)


class ElidingLabel(QLabel):
    """An eliding version of QLabel"""

    def __init__(self, text=""):
        super().__init__()

        self.setSizePolicy(QSizePolicy.Policy.Expanding,
                           QSizePolicy.Policy.Preferred)
        self.setText(text)

    def setText(self, text):
        self.content = text
        self.update()

    def paintEvent(self, event):
        super().paintEvent(event)

        painter = QPainter(self)
        font_metrics = painter.fontMetrics()
        content_width = font_metrics.horizontalAdvance(self.content)

        text_layout = QTextLayout(self.content, painter.font())
        text_layout.beginLayout()

        line = text_layout.createLine()
        line.setLineWidth(self.width())

        if content_width > self.width():
            elided_content = font_metrics.elidedText(
                self.content, Qt.TextElideMode.ElideRight, self.width())
            painter.drawText(QPointF(0, font_metrics.ascent()), elided_content)
        else:
            painter.drawText(QPointF(self.width() - content_width,
                             font_metrics.ascent()), self.content)

        text_layout.endLayout()


class MainWindow(QWidget):
    """The main class containing all widgets"""

    def __init__(self):
        super().__init__()

        # store state to skip parts of some updates
        self.skip_playlist_update = False
        self.last_currentsong = None
        self.skip_progress_update = False
        self.song_progress = None
        self.playlists = None

        self.client = MPDClient2()
        self.notifier = DesktopNotifier()
        self.async_init()

    @asyncSlot()
    async def async_init(self):
        await self.init_client()

        self.init_gui()
        self.init_shortcuts()

        try:
            await asyncio.gather(
                self.check_for_updates(),
                self.check_for_progress()
            )
        except asyncio.exceptions.CancelledError:
            pass

    async def init_client(self):
        await self.client.connect(mpd_host, mpd_port)
        if mpd_passwd != "":
            await self.client.password(mpd_passwd)

    def init_gui(self):
        grid = QGridLayout()

        # playback controls
        self.btn_prev = QPushButton("Prev")
        self.btn_prev.clicked.connect(lambda _: self.client.previous())
        # self.btn_prev.setSizePolicy(
        #    QSizePolicy.Policy.Preferred,
        #    QSizePolicy.Policy.Expanding)
        grid.addWidget(self.btn_prev, 0, 0, 2, 1)

        self.btn_toggle = QPushButton("Play")
        self.btn_toggle.clicked.connect(lambda _: self.client.toggle())
        grid.addWidget(self.btn_toggle, 0, 1, 2, 1)

        self.btn_stop = QPushButton("Stop")
        self.btn_stop.clicked.connect(lambda _: self.client.stop())
        grid.addWidget(self.btn_stop, 0, 2, 2, 1)

        self.btn_next = QPushButton("Next")
        self.btn_next.clicked.connect(lambda _: self.client.next())
        grid.addWidget(self.btn_next, 0, 3, 2, 1)

        self.btn_random = QPushButton("Random")
        self.btn_random.setCheckable(True)
        self.btn_random.clicked.connect(lambda _: self.client.random(
            1 if self.btn_random.isChecked() else 0))
        grid.addWidget(self.btn_random, 0, 4, 2, 1)

        # currently playing labels
        grid.setColumnStretch(5, 10)

        self.lbl_current_title = ElidingLabel("—")
        self.lbl_current_title.setStyleSheet("font: bold 20px;")
        self.lbl_current_title.setAlignment(Qt.AlignmentFlag.AlignRight)
        grid.addWidget(self.lbl_current_title, 0, 5, 1, 2)

        self.lbl_current_artist_album = ElidingLabel("—  •  —")
        self.lbl_current_artist_album.setAlignment(Qt.AlignmentFlag.AlignRight)
        grid.addWidget(self.lbl_current_artist_album, 1, 5, 1, 2)

        # song progress
        progress_widget = QWidget()
        progress_layout = QHBoxLayout()
        progress_widget.setLayout(progress_layout)

        self.sld_progress = QSlider(Qt.Orientation.Horizontal)
        self.sld_progress.setMinimum(0)

        def sld_progress_valueChanged():
            value = self.sld_progress.value()
            if self.song_progress != value:
                logging.debug("song progress slider set to: " + str(value))
                self.client.seekcur(value)

        #self.sld_progress.valueChanged.connect(sld_progress_valueChanged)
        self.sld_progress.sliderMoved.connect(sld_progress_valueChanged)
        progress_layout.addWidget(self.sld_progress)

        self.lbl_progress = QLabel("— / —")
        self.lbl_progress.setAlignment(Qt.AlignmentFlag.AlignRight)
        progress_layout.addWidget(self.lbl_progress)

        grid.addWidget(progress_widget, 2, 0, 1, 7)

        # tabs
        self.tabs = QTabWidget()
        grid.addWidget(self.tabs, 3, 0, 1, 7)

        # current play queue
        self.lst_queue = self.create_lst_queue()
        self.tabs.addTab(self.lst_queue, "Queue")

        # current album cover
        self.cvr_current = CoverWidget()
        self.tabs.addTab(self.cvr_current, "Cover")

        # current song info
        self.lbl_current_info = QTextEdit("")
        self.lbl_current_info.setReadOnly(True)
        self.tabs.addTab(self.lbl_current_info, "Info")

        # search
        self.tab_search = self.create_tab_search()
        self.tabs.addTab(self.tab_search, "Search")

        # playlists
        self.tab_playlists = self.create_tab_playlists()
        self.tabs.addTab(self.tab_playlists, "Playlists")

        self.setLayout(grid)
        self.setWindowTitle("cmpdc")
        self.show()

    def init_shortcuts(self):
        # show tabs
        tab1 = QShortcut(QKeySequence("Ctrl+1"), self)
        tab1.activated.connect(lambda: self.tabs.setCurrentIndex(0))
        tab2 = QShortcut(QKeySequence("Ctrl+2"), self)
        tab2.activated.connect(lambda: self.tabs.setCurrentIndex(1))
        tab3 = QShortcut(QKeySequence("Ctrl+3"), self)
        tab3.activated.connect(lambda: self.tabs.setCurrentIndex(2))
        tab4 = QShortcut(QKeySequence("Ctrl+4"), self)
        tab4.activated.connect(lambda: self.tabs.setCurrentIndex(3))
        tab5 = QShortcut(QKeySequence("Ctrl+5"), self)
        tab5.activated.connect(lambda: self.tabs.setCurrentIndex(4))

        center_current = QShortcut(QKeySequence("Ctrl+C"), self)
        center_current.activated.connect(self.center_on_current_song)

        update_db = QShortcut(QKeySequence("F5"), self)
        update_db.activated.connect(lambda: self.client.update())

        # control playback
        toggle = QShortcut(QKeySequence("Ctrl+Space"), self)
        toggle.activated.connect(lambda: self.client.toggle())
        toggle = QShortcut(QKeySequence("Ctrl+Left"), self)
        toggle.activated.connect(lambda: self.client.previous())
        toggle = QShortcut(QKeySequence("Ctrl+Right"), self)
        toggle.activated.connect(lambda: self.client.next())

        # kill/restart mpd
        kill = QShortcut(QKeySequence("Ctrl+Shift+K"), self)
        kill.activated.connect(lambda: os.system("systemctl --user kill -s SIGKILL mpd.service; systemctl --user start mpd.service"))

        # save queue
        def save_queue_dialog():
            dlg = QDialog(self)
            dlg.setWindowTitle("Save Queue As")
            vbox = QVBoxLayout(dlg)

            cmb_playlist = QComboBox()
            cmb_playlist.setSizePolicy(
                QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
            cmb_playlist.setEditable(True)
            cmb_playlist.setInsertPolicy(QComboBox.InsertPolicy.InsertAtBottom)
            vbox.addWidget(cmb_playlist)

            for p in self.playlists:
                cmb_playlist.addItem(p["playlist"])

            QBtn = QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
            button_box = QDialogButtonBox(QBtn)
            button_box.accepted.connect(
                lambda: (self.client.rm_save(cmb_playlist.currentText()), dlg.close()))
            button_box.rejected.connect(lambda: dlg.close())
            vbox.addWidget(button_box)

            dlg.exec()

        save_queue = QShortcut(QKeySequence("Ctrl+S"), self)
        save_queue.activated.connect(lambda: save_queue_dialog())

    def create_lst_queue(self):
        lst_queue = QListWidget()
        lst_queue.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        lst_queue.setSelectionMode(
            QAbstractItemView.SelectionMode.ContiguousSelection)
        lst_queue.itemDoubleClicked.connect(
            lambda i: self.client.play(self.lst_queue.row(i)))

        # drop event
        lst_queue.dropEvent_old = lst_queue.dropEvent

        def dropEvent_new(event):
            old_row = event.source().currentRow()
            lst_queue.dropEvent_old(event)
            new_row = event.source().currentRow()
            self.skip_playlist_update = True
            self.client.move(old_row, new_row)
        lst_queue.dropEvent = dropEvent_new

        # key press event
        lst_queue.keyPressEvent_old = lst_queue.keyPressEvent

        def keyPressEvent_new(event):
            if event.key() == Qt.Key.Key_Delete:
                indexes = sorted(lst_queue.selectedIndexes(), reverse=True)
                self.skip_playlist_update = True

                # delete songs from widget
                for current_index in indexes:
                    lst_queue.takeItem(current_index.row())

                # and from the mpd queue
                if len(indexes) == 1:
                    self.client.delete(indexes[0].row())
                elif len(indexes) > 1:
                    self.client.delete((indexes[-1].row(), indexes[0].row()+1))
            elif event.key() == Qt.Key.Key_Space or event.key() == Qt.Key.Key_Return:
                self.client.play(self.lst_queue.currentRow())
            else:
                lst_queue.keyPressEvent_old(event)
        lst_queue.keyPressEvent = keyPressEvent_new

        return lst_queue

    def create_tab_search(self):
        tab_search = QListWidget()
        # tab_search.itemDoubleClicked.connect(
        #    lambda i: self.client.play(self.lst_queue.row(i)))
        vbox = QVBoxLayout()
        tab_search.setLayout(vbox)

        self.edt_search = QLineEdit()
        self.edt_search.returnPressed.connect(lambda: self.update_lst_search())
        vbox.addWidget(self.edt_search)

        self.lst_search = QListWidget()
        self.lst_search.setSelectionMode(
            QAbstractItemView.SelectionMode.ExtendedSelection)
        self.lst_search.itemDoubleClicked.connect(
            lambda i: self.client.add(self.search_results[self.lst_search.row(i)]["file"]))
        vbox.addWidget(self.lst_search)

        # key press event
        self.lst_search.keyPressEvent_old = self.lst_search.keyPressEvent

        def keyPressEvent_new(event):
            # replace queue
            if event.modifiers() & Qt.KeyboardModifier.ControlModifier and event.key() == Qt.Key.Key_R:
                indexes = sorted(self.lst_search.selectedIndexes())
                if len(indexes) > 0:
                    self.client.clear()
                    for index in indexes:
                        self.client.add(
                            self.search_results[index.row()]["file"])
                    self.client.play()

            # add to queue
            elif event.modifiers() & Qt.KeyboardModifier.ControlModifier and event.key() == Qt.Key.Key_P:
                indexes = sorted(self.lst_search.selectedIndexes())
                for index in indexes:
                    self.client.add(self.search_results[index.row()]["file"])

            else:
                self.lst_search.keyPressEvent_old(event)
        self.lst_search.keyPressEvent = keyPressEvent_new

        return tab_search

    def create_tab_playlists(self):
        tab_playlists = QWidget()
        vbox = QVBoxLayout()
        buttons_playlists = QWidget()
        hbox = QHBoxLayout()

        self.cmb_playlist = QComboBox()
        self.cmb_playlist.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Preferred)
        self.cmb_playlist.currentIndexChanged.connect(
            lambda: self.show_stored_playlist())
        hbox.addWidget(self.cmb_playlist)

        @asyncSlot()
        async def load_playlist(playlist):
            await self.client.clear()
            await self.client.load(playlist)
            self.client.play()

        self.btn_playlist_play = QPushButton("Play")
        self.btn_playlist_play.clicked.connect(
            lambda: load_playlist(self.cmb_playlist.currentText()))
        hbox.addWidget(self.btn_playlist_play)

        self.btn_playlist_delete = QPushButton("Delete")
        self.btn_playlist_delete.clicked.connect(
            lambda: self.client.rm(self.cmb_playlist.currentText()))
        hbox.addWidget(self.btn_playlist_delete)

        buttons_playlists.setLayout(hbox)
        vbox.addWidget(buttons_playlists)

        self.lst_playlist = QListWidget()
        vbox.addWidget(self.lst_playlist)

        tab_playlists.setLayout(vbox)
        return tab_playlists

    async def check_for_progress(self):
        """Causes the song progress to be updated every second"""

        while True:
            try:
                if not self.skip_progress_update:
                    await self.update_progress()
            except Exception as e:
                logging.error(e)
            finally:
                await asyncio.sleep(1)

    async def check_for_updates(self):
        """Check for state changes"""

        asyncio.gather(
            self.update_player(),
            self.update_progress(),
            self.update_options(),
            self.update_playlist(),
            self.update_stored_playlist()
        )

        async for subsystems in self.client.idle():
            #logging.debug("Change in ", subsystems)
            if "player" in subsystems:
                await self.update_player()
                await self.update_progress()
            if "options" in subsystems:
                await self.update_options()
            if "playlist" in subsystems:
                await self.update_playlist()
            if "stored_playlist" in subsystems:
                await self.update_stored_playlist()

    async def update_progress(self):
        """Update the song progress widgets"""
        def format_queue_position(status):
            try:
                song = int(status["song"]) + 1
                return (str(song) + " / " + status["playlistlength"])
            except Exception as e:
                logging.error(e)
                return "— / —"

        try:
            status = await self.client.status()
            song_progress = int(float(status["elapsed"]))
            song_duration = int(float(status["duration"]))
            self.song_progress = song_progress
            self.sld_progress.setMaximum(song_duration)
            self.sld_progress.setValue(song_progress)
            self.lbl_progress.setText(
                format_duration(song_progress) + " / " +
                format_duration(song_duration) +
                "  (" + format_queue_position(status) + ")"
            )
        except Exception as e:
            logging.warning(e)
            self.sld_progress.setValue(0)
            self.lbl_progress.setText("— / —  (— / —)")

    async def update_player(self):
        """Update the widgets when the player subsystem has changed"""

        status = await self.client.status()

        # change the label of the play/pause button
        if status["state"] == "play":
            self.btn_toggle.setText("Pause")
            self.skip_progress_update = False
        else:
            self.btn_toggle.setText("Play")
            self.skip_progress_update = True

        # new song ?
        currentsong = await self.client.currentsong()
        if self.last_currentsong != currentsong:
            self.last_currentsong = currentsong

            title = currentsong["title"] if "title" in currentsong else (currentsong["file"] if "file" in currentsong else "—")
            artist = currentsong["artist"] if "artist" in currentsong else "—"
            album = currentsong["album"] if "album" in currentsong else "—"

            # move to current song
            self.center_on_current_song(currentsong)

            # display song title/album/artist
            self.lbl_current_title.setText(title)
            self.lbl_current_artist_album.setText(f"{artist}  •  {album}")

            # show desktop notification
            if desktop_notification:
                await self.notifier.send(title=title, message=f"{artist}  •  {album}", icon="")

            # try to get current cover from mpd
            albumart = await self.client.albumart_or_none(currentsong=currentsong)
            if albumart is None:
                logging.debug(
                    "albumart() returned no picture, trying readpicture()")
                albumart = await self.client.readpicture_or_none(currentsong=currentsong)

            # get detailed song info using mutagen
            if "file" in currentsong:
                file_path = os.path.join(music_directory, currentsong["file"])
                try:
                    mutagen_file = mutagen.File(file_path)
                    mutagen_info = mutagen_file.pprint()

                    # there doesn't seem to be a format independent way to access tag data,
                    # therefore the pprint() output is used and gets modified
                    text = \
                        "<h3>File</h3>" + file_path + \
                        "<h3>Audio</h3>" + \
                        re.sub("\n.+=",
                               lambda s: ("<h3>" + s.group(0).replace("\n", "").capitalize() + "</h3>").replace("=</h3>", "</h3>"), mutagen_info)
                    text = text.replace("\n", "<br/>")
                    self.lbl_current_info.setHtml(text)

                    # if mpd has no cover, try getting one using mutagen
                    try:
                        if albumart is None:
                            logging.debug(
                                "readpicture() returned no picture, trying mutagen")
                            albumart = mutagen_file.pictures[0].data
                    except Exception as e:
                        logging.warning(e)
                except Exception as e:
                    self.lbl_current_info.setText("")
                    logging.warning(
                        "Failed to obtain song information using mutagen: " + str(e))

                # if neither mpd nor mutagen has a cover, look in the filesystem
                if albumart is None:
                    dir_path = os.path.dirname(file_path)
                    logging.debug(
                        "mutagen returned no picture, looking in " + dir_path)
                    albumart = albumart_file_or_none(dir_path)

            # set background of play queue to cover
            # if albumart != None:
            #    with open("./cover", "wb") as f:
            #        f.write(albumart)
            #    self.lst_queue.setStyleSheet("background: url(./cover)")
            # else:
            #    pass

            # show current cover
            image = QImage()
            image.loadFromData(albumart)
            pixmap = QPixmap(image)
            self.cvr_current.setPixmap(pixmap)
            self.cvr_current.repaint()

    async def update_playlist(self):
        """Update the widgets when the playlist subsystem has changed"""

        if self.skip_playlist_update:
            self.skip_playlist_update = False
            return

        playlist = await self.client.playlistinfo()

        # clear self.lst_queue
        for i in range(self.lst_queue.count()-1, -1, -1):
            self.lst_queue.takeItem(i)

        for track in playlist:
            self.lst_queue.addItem(format_song(track))

    async def update_options(self):
        """Update the widgets when the options subsystem has changed"""

        status = await self.client.status()
        if "random" in status:
            self.btn_random.setChecked(status["random"] == "1")

    async def update_stored_playlist(self):
        self.playlists = await self.client.listplaylists()

        self.cmb_playlist.clear()
        for p in self.playlists:
            self.cmb_playlist.addItem(p["playlist"])

        self.show_stored_playlist()

    @asyncSlot()
    async def show_stored_playlist(self):
        playlist = await self.client.listplaylistinfo(self.cmb_playlist.currentText())

        for i in range(self.lst_playlist.count()-1, -1, -1):
            self.lst_playlist.takeItem(i)

        for track in playlist:
            self.lst_playlist.addItem(format_song(track))

    @asyncSlot()
    async def update_lst_search(self):
        self.search_results = await self.client.search("any", self.edt_search.text())

        for i in range(self.lst_search.count()-1, -1, -1):
            self.lst_search.takeItem(i)

        for track in self.search_results:
            self.lst_search.addItem(format_song(track))

    @asyncSlot()
    async def center_on_current_song(self, currentsong=None):
        if currentsong is None:
            currentsong = await self.client.currentsong()

        if "pos" in currentsong:
            self.lst_queue.setCurrentRow(int(currentsong["pos"]))
            self.lst_queue.scrollToItem(
                self.lst_queue.item(int(currentsong["pos"])),
                QAbstractItemView.ScrollHint.PositionAtCenter
            )

    @asyncClose
    async def closeEvent(self, event):
        pass


async def main():
    def close_future(future, loop):
        loop.call_later(10, future.cancel)
        future.cancel()

    loop = asyncio.get_event_loop()
    future = asyncio.Future()

    app = QApplication.instance()
    if hasattr(app, "aboutToQuit"):
        getattr(app, "aboutToQuit").connect(
            functools.partial(close_future, future, loop)
        )

    app.setStyle(theme)

    main_window = MainWindow()
    main_window.show()

    await future
    return True


if __name__ == "__main__":
    try:
        qasync.run(main())
    except asyncio.exceptions.CancelledError:
        sys.exit(0)
