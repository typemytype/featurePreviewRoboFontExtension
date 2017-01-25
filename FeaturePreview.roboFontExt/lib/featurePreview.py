from vanilla import *

import os
import tempfile

from compositor import Font as FeatureFont
from compositor.textUtilities import convertCase

from defconAppKit.windows.baseWindow import BaseWindowController
from defconAppKit.controls.openTypeControlsView import OpenTypeControlsView
from defconAppKit.controls.glyphSequenceEditText import GlyphSequenceEditText
from defconAppKit.controls.glyphLineView import GlyphLineView

from fontCompiler.compiler import FontCompilerOptions
from fontCompiler.emptyCompiler import EmptyOTFCompiler
from fontCompiler.tools.compileTools import EmbeddedFDK


class FeatureTester(BaseWindowController):

    def __init__(self, font):
        if font is None:
            print "An open UFO is needed"
            return
        roboFabFont = font
        font = font.naked()
        self.font = font
        self.featureFont = None

        topHeight = 40
        left = 160

        self.w = Window((700, 400), "Feature Preview", minSize=(300, 300))

        previewGroup = Group((0, 0, -0, -0))
        self.glyphLineInputPosSize = (10, 10, -85, 22)
        self.glyphLineInputPosSizeWithSpinner = (10, 10, -106, 22)
        previewGroup.glyphNameInput = self.glyphLineInput = GlyphSequenceEditText(self.glyphLineInputPosSize, font, callback=self.glyphLineViewInputCallback)
        previewGroup.progressSpinner = self.glyphLineProgressSpinner = ProgressSpinner((-98, 13, 16, 16), sizeStyle="small")
        previewGroup.updateButton = self.glyphLineUpdateButton = Button((-75, 11, -10, 20), "Update", callback=self.updateFeatureFontCallback)

        self.w.pg = previewGroup

        # tab container
        self.w.previewTabs = Tabs((left, topHeight, -0, -0), ["Preview", "Records"], showTabs=False)
        # line view
        self.w.previewTabs[0].lineView = self.glyphLineView = GlyphLineView((0, 0, -0, -0), showPointSizePlacard=True)
        # records
        columnDescriptions = [
            dict(title="Name", width=100, minWidth=100, maxWidth=300),
            dict(title="XP", width=50),
            dict(title="YP", width=50),
            dict(title="XA", width=50),
            dict(title="YA", width=50),
            dict(title="Alternates", width=100, minWidth=100, maxWidth=300)
        ]
        self.w.previewTabs[1].recordsList = self.glyphRecordsList = List((0, 0, -0, -0), [], columnDescriptions=columnDescriptions,
                showColumnTitles=True, drawVerticalLines=True, drawFocusRing=False)
        # controls
        self.w.controlsView = self.glyphLineControls = OpenTypeControlsView((0, topHeight, left+1, 0), self.glyphLineViewControlsCallback)

        self.font.addObserver(self, "_fontChanged", "Font.Changed")

        self.w.setDefaultButton(self.glyphLineUpdateButton)
        self.w.bind("close", self.windowClose)
        self.setUpBaseWindowBehavior()

        document = roboFabFont.document()
        if document is not None:
            document.addWindowController_(self.w.getNSWindowController())

        # Somehow being attached to an NSDocument makes the vanilla.Window autosaveName argument not work.
        self.w._window.setFrameAutosaveName_("featurePreviewRoboFontExtension")

        self.w.open()

        self.updateFeatureFontCallback(None)

    def windowClose(self, sender):
        self.destroyFeatureFont()
        self.font.removeObserver(self, "Font.Changed")

    def destroyFeatureFont(self):
        if self.featureFont is not None:
            path = self.featureFont.path
            self.featureFont = None
            os.remove(path)

    def _fontChanged(self, notification):
        self.w.setDefaultButton(self.glyphLineUpdateButton)
        # self.glyphLineUpdateButton.enable(True)

    def glyphLineViewInputCallback(self, sender):
        self.updateGlyphLineView()

    def updateFeatureFontCallback(self, sender):
        self._compileFeatureFont()
        self.updateGlyphLineViewViewControls()
        self.updateGlyphLineView()

    def glyphLineViewControlsCallback(self, sender):
        self.updateGlyphLineView()

    def _compileFeatureFont(self, showReport=True):
        # reposition the text field
        self.glyphLineInput.setPosSize(self.glyphLineInputPosSizeWithSpinner)
        self.glyphLineInput.getNSTextField().superview().display()
        # start the progress
        self.glyphLineProgressSpinner.start()
        # compile
        path = tempfile.mkstemp()[1]
        compiler = EmptyOTFCompiler()
        # clean up
        if self.font.info.openTypeOS2WinDescent is not None and self.font.info.openTypeOS2WinDescent < 0:
            self.font.info.openTypeOS2WinDescent = abs(self.font.info.openTypeOS2WinDescent)
        self.font.info.postscriptNominalWidthX = None
        options = FontCompilerOptions()
        options.outputPath = path
        options.fdk = EmbeddedFDK()
        reports = compiler.compile(self.font, options)
        # load the compiled font
        if os.path.exists(path) and reports["makeotf"] is not None and "makeotfexe [FATAL]" not in reports["makeotf"]:
            self.featureFont = FeatureFont(path)
        else:
            self.featureFont = None

            if showReport:
                report = []
                if reports["makeotf"] is not None:
                    for line in reports["makeotf"].splitlines():
                        if line.startswith("makeotfexe [NOTE] Wrote new font file "):
                            continue
                        report.append(line)
                self.showMessage("Error while compiling features", "\n".join(report))

        # stop the progress
        self.glyphLineProgressSpinner.stop()
        # color the update button
        window = self.w.getNSWindow()
        window.setDefaultButtonCell_(None)
        # self.glyphLineUpdateButton.enable(False)
        # reposition the text field
        self.glyphLineInput.setPosSize(self.glyphLineInputPosSize)

    def updateGlyphLineView(self):
        # get the settings
        settings = self.glyphLineControls.get()
        # set the display mode
        mode = settings["mode"]
        if mode == "preview":
            self.w.previewTabs.set(0)
        else:
            self.w.previewTabs.set(1)
        # set the direction
        self.glyphLineView.setRightToLeft(settings["rightToLeft"])
        # get the typed glyphs
        glyphs = self.glyphLineInput.get()
        # set into the view
        case = settings["case"]
        if self.featureFont is None:
            # convert case
            if case != "unchanged":
                # the case converter expects a slightly
                # more strict set of mappings than the
                # ones provided in font.unicodeData.
                # so, make them.
                cmap = {}
                reversedCMAP = {}
                for uniValue, glyphName in self.font.unicodeData.items():
                    cmap[uniValue] = glyphName[0]
                    reversedCMAP[glyphName[0]] = [uniValue]
                # transform to glyph names
                glyphNames = [glyph.name for glyph in glyphs]
                # convert
                glyphNames = convertCase(case, glyphNames, cmap, reversedCMAP, None, ".notdef")
                # back to glyphs
                glyphs = [self.font[glyphName] for glyphName in glyphNames if glyphName in self.font]
            # set the glyphs
            self.glyphLineView.set(glyphs)
            records = [dict(Name=glyph.name, XP=0, YP=0, XA=0, YA=0, Alternates="") for glyph in glyphs]
            self.glyphRecordsList.set(records)
        else:
            # get the settings
            script = settings["script"]
            language = settings["language"]
            rightToLeft = settings["rightToLeft"]
            case = settings["case"]
            for tag, state in settings["gsub"].items():
                self.featureFont.gsub.setFeatureState(tag, state)
            for tag, state in settings["gpos"].items():
                self.featureFont.gpos.setFeatureState(tag, state)
            # convert to glyph names
            glyphNames = [glyph.name for glyph in glyphs]
            # process
            glyphRecords = self.featureFont.process(glyphNames, script=script, langSys=language, rightToLeft=rightToLeft, case=case)
            # set the UFO's glyphs into the records
            finalRecords = []
            for glyphRecord in glyphRecords:
                if glyphRecord.glyphName not in self.font:
                    continue
                glyphRecord.glyph = self.font[glyphRecord.glyphName]
                finalRecords.append(glyphRecord)
            # set the records
            self.glyphLineView.set(finalRecords)
            records = [dict(Name=record.glyph.name, XP=record.xPlacement, YP=record.yPlacement, XA=record.xAdvance, YA=record.yAdvance, Alternates=", ".join(record.alternates)) for record in finalRecords]
            self.glyphRecordsList.set(records)

    def updateGlyphLineViewViewControls(self):
        if self.featureFont is not None:
            existingStates = self.glyphLineControls.get()
            # GSUB
            if self.featureFont.gsub is not None:
                for tag in self.featureFont.gsub.getFeatureList():
                    state = existingStates["gsub"].get(tag, False)
                    self.featureFont.gsub.setFeatureState(tag, state)
            # GPOS
            if self.featureFont.gpos is not None:
                for tag in self.featureFont.gpos.getFeatureList():
                    state = existingStates["gpos"].get(tag, False)
                    self.featureFont.gpos.setFeatureState(tag, state)
        self.glyphLineControls.setFont(self.featureFont)

if __name__ is "__main__":
    FeatureTester(font=CurrentFont())
