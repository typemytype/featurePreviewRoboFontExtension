from vanilla import *
import AppKit
import os

from compositor.textUtilities import convertCase

from defconAppKit.windows.baseWindow import BaseWindowController
from defconAppKit.controls.openTypeControlsView import OpenTypeControlsView
from defconAppKit.controls.glyphSequenceEditText import GlyphSequenceEditText
from defconAppKit.controls.glyphLineView import GlyphLineView

from ufo2fdk.makeotfParts import forceAbsoluteIncludesInFeatures, extractFeaturesAndTables
from ufo2ft.featureWriters.kernFeatureWriter import KernFeatureWriter, ast

import uharfbuzz as hb
from fontTools import unicodedata
from fontTools.feaLib.parser import Parser as FeatureParser
from fontTools.fontBuilder import FontBuilder
import io


class GlyphRecord(object):

    def __init__(self, glyph=None, xPlacement=0, yPlacement=0, xAdvance=0, yAdvance=0, alternates=None):
        self.glyph = glyph
        self.advanceWidth = 0
        self.advanceHeight = 0
        if glyph is not None:
            self.advanceWidth = glyph.width
            self.advanceHeight = glyph.height
        self.xPlacement = xPlacement
        self.yPlacement = yPlacement
        self.xAdvance = xAdvance - self.advanceWidth
        self.yAdvance = yAdvance - self.advanceHeight
        if alternates is None:
            alternates = []
        self.alternates = alternates


class Table(object):

    def wrapValue(self, attribute, value):
        def callback():
            return value
        setattr(self, attribute, callback)


class FeatureFont(object):

    def __init__(self, font):
        self.font = font
        self.buildBinaryFont()        
        self.loadFeatures()
        self.loadStylisticSetNames()
        self.loadAlternates()
        self.featureStates = dict()

    def buildBinaryFont(self):
        font = self.font
        cmap = {uni: names[0] for uni, names in font.unicodeData.items()}
        glyphOrder = sorted(set(font.glyphOrder) | set(cmap.values()))

        ff = FontBuilder(font.info.unitsPerEm, isTTF=True)
        ff.setupGlyphOrder(glyphOrder)
        if cmap:
            ff.setupCharacterMap(cmap)
        ff.addOpenTypeFeatures(self._getFeatureText(font))
        ff.setupHorizontalMetrics({gn: (int(round(font[gn].width)), int(round(font[gn].height))) for gn in glyphOrder})
        ff.setupHorizontalHeader(ascent=int(round(font.info.ascender)), descent=int(round(font.info.descender)))
        data = io.BytesIO()
        ff.save(data)
        self.source = ff.font
        self._data = data.getvalue()
        
    def loadFeatures(self):
        ft = self.source
        self.gpos = None
        if "GPOS" in ft and ft["GPOS"].table.FeatureList is not None:
            self.gpos = Table()
            GPOSFeatureTags = set()
            GPOSScriptList = set()
            GPOSLanguageList = set()
            for record in ft["GPOS"].table.FeatureList.FeatureRecord:
                GPOSFeatureTags.add(record.FeatureTag)
            for record in ft["GPOS"].table.ScriptList.ScriptRecord:
                GPOSScriptList.add(record.ScriptTag)
                script = record.Script
                if script.LangSysCount:
                    for langSysRecord in script.LangSysRecord:
                        GPOSLanguageList.add(langSysRecord.LangSysTag)

            self.gpos.wrapValue("getFeatureList", GPOSFeatureTags)
            self.gpos.wrapValue("getScriptList", GPOSScriptList)
            self.gpos.wrapValue("getLanguageList", GPOSLanguageList)
            self.gpos.getFeatureState = self.getFeatureState
            self.gpos.setFeatureState = self.setFeatureState

        self.gsub = None
        if "GSUB" in ft and ft["GSUB"].table.FeatureList is not None:
            self.gsub = Table()
            GSUBFeatureTags = set()
            GSUBScriptList = set()
            GSUBLanguageList = set()
            for record in ft["GSUB"].table.FeatureList.FeatureRecord:
                GSUBFeatureTags.add(record.FeatureTag)
            for record in ft["GSUB"].table.ScriptList.ScriptRecord:
                GSUBScriptList.add(record.ScriptTag)
                script = record.Script
                if script.LangSysCount:
                    for langSysRecord in script.LangSysRecord:
                        GSUBLanguageList.add(langSysRecord.LangSysTag)

            self.gsub.wrapValue("getFeatureList", GSUBFeatureTags)
            self.gsub.wrapValue("getScriptList", GSUBScriptList)
            self.gsub.wrapValue("getLanguageList", GSUBLanguageList)
            self.gsub.getFeatureState = self.getFeatureState
            self.gsub.setFeatureState = self.setFeatureState

    def loadStylisticSetNames(self):
        ft = self.source
        self.stylisticSetNames = dict()
        if "GSUB" in ft and ft["GSUB"].table.FeatureList is not None:
            # names
            nameIDs = {}
            if "name" in ft:
                for nameRecord in ft["name"].names:
                    nameID = nameRecord.nameID
                    platformID = nameRecord.platformID
                    platEncID = nameRecord.platEncID
                    langID = nameRecord.langID
                    nameIDs[nameID, platformID, platEncID, langID] = nameRecord.toUnicode()
            for record in ft["GSUB"].table.FeatureList.FeatureRecord:
                params = record.Feature.FeatureParams
                if hasattr(params, "UINameID"):
                    ssNameID = params.UINameID
                    namePriority = [(ssNameID, 1, 0, 0), (ssNameID, 1, None, None), (ssNameID, 3, 1, 1033), (ssNameID, 3, None, None)]
                    ssName = self._skimNameIDs(nameIDs, namePriority)
                    if ssName:
                        self.stylisticSetNames[record.FeatureTag] = ssName

    def loadAlternates(self):
        self.alternates = {}
        ft = self.source
        if "GSUB" in ft:
            lookup = ft["GSUB"].table.LookupList.Lookup
            for record in ft["GSUB"].table.FeatureList.FeatureRecord:
                if record.FeatureTag == "aalt":
                    for lookupIndex in record.Feature.LookupListIndex:
                        for subTable in lookup[lookupIndex].SubTable:
                            if subTable.LookupType == 1:
                                for key, value in subTable.mapping.items():
                                    if key not in self.alternates:
                                        self.alternates[key] = set()
                                    self.alternates[key].add(value)
                            elif subTable.LookupType == 3:
                                for key, values in subTable.alternates.items():
                                    if key not in self.alternates:
                                        self.alternates[key] = set()
                                    self.alternates[key] |= set(values)

    def process(self, text, script="latn", langSys=None, rightToLeft=None, case="unchanged", logger=None):
        if not text:
            return []
        if case == "upper":
            text = text.upper()
        elif case == "lower":
            text = text.lower()

        for tag in ["init", "medi", "fina"]:
            if tag in self.featureStates and not self.featureStates[tag]:
                del self.featureStates[tag]

        buf = hb.Buffer()
        if script and script != "DFLT":
            buf.script = script
        if langSys is not None:
            buf.language = langSys
        if rightToLeft is not None:
            if rightToLeft:
                buf.direction = "rtl"
            else:
                buf.direction = "ltr"
        buf.add_codepoints([ord(c) for c in text])
        buf.guess_segment_properties()

        face = hb.Face(self._data)
        harfbuzzFont = hb.Font(face)
        hb.shape(harfbuzzFont, buf, self.featureStates)

        infos = buf.glyph_infos
        positions = buf.glyph_positions

        glyphRecords = []

        for info, pos in zip(infos, positions):
            index = info.codepoint
            glyphName = self.source.getGlyphName(index)
            glyphRecords.append(GlyphRecord(
                self.font[glyphName],
                pos.x_offset,
                pos.y_offset,
                pos.x_advance,
                pos.y_advance,
                alternates=sorted(self.alternates.get(glyphName, []))
            ))
        return glyphRecords

    def setFeatureState(self, featureTag, state):
        self.featureStates[featureTag] = state

    def getFeatureState(self, featureTag):
        return self.featureStates.get(featureTag, False)

    def getLanguageList(self):
        gsub = set()
        gpos = set()
        if self.gsub is not None:
            gsub = self.gsub.getLanguageList()
        if self.gpos is not None:
            gpos = self.gpos.getLanguageList()
        return sorted(gsub | gpos)

    def getScriptList(self):
        gsub = set()
        gpos = set()
        if self.gsub is not None:
            gsub = self.gsub.getScriptList()
        if self.gpos is not None:
            gpos = self.gpos.getScriptList()
        return sorted(gsub | gpos)

    def _getFeatureText(self, font):
        if font.path is None:
            fea = font.features.text
            featuretags, _ = extractFeaturesAndTables(fea)
        else:
            fea = forceAbsoluteIncludesInFeatures(font.features.text, os.path.dirname(font.path))
            featuretags, _ = extractFeaturesAndTables(fea, scannedFiles=[os.path.join(font.path, "features.fea")])
        if "kern" not in featuretags:
            languageSystems = set()
            for glyph in font:
                for uni in glyph.unicodes:
                    scriptTag = unicodedata.script(chr(uni))
                    languageSystems.add(scriptTag.lower())
            languageSystems -= set(["common", "zyyy", "zinh", "zzzz"])
            languageSystems = ["DFLT"] + sorted(languageSystems)

            data = io.StringIO(fea)
            feaParser = FeatureParser(data, set(font.keys()))
            feaFile = feaParser.parse()
            existingLanguageSystems = set([st.script for st in feaFile.statements if isinstance(st, ast.LanguageSystemStatement)])
            for script in reversed(languageSystems):
                if script not in existingLanguageSystems:
                    feaFile.statements.insert(0, ast.LanguageSystemStatement(script=script, language="dflt"))
            writer = KernFeatureWriter()
            writer.write(font, feaFile)
            # clean up
            feaFile.statements.pop(0)
            for script in languageSystems:
                feaFile.statements.pop(0)

            def removeScriptlanguage(feaFile):
                for statement in list(feaFile.statements):
                    if hasattr(statement, "statements"):
                        removeScriptlanguage(statement)
                    if isinstance(statement, (ast.ScriptStatement, ast.LanguageStatement)):
                        feaFile.statements.remove(statement)
            removeScriptlanguage(feaFile)
            fea = feaFile.asFea()
        return fea

    def _skimNameIDs(self, nameIDs, priority):
        for (nameID, platformID, platEncID, langID) in priority:
            for (nID, pID, pEID, lID), text in nameIDs.items():
                if nID != nameID:
                    continue
                if pID != platformID and platformID is not None:
                    continue
                if pEID != platEncID and platEncID is not None:
                    continue
                if lID != langID and langID is not None:
                    continue
                return text


class FeatureTester(BaseWindowController):
    
    featureFontClass = FeatureFont
        
    def __init__(self, font):
        if font is None:
            print("An open UFO is needed")
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
        previewGroup.glyphNameInput = self.glyphLineInput = EditText(self.glyphLineInputPosSize, callback=self.glyphLineViewInputCallback)
        previewGroup.progressSpinner = self.glyphLineProgressSpinner = ProgressSpinner((-98, 13, 16, 16), sizeStyle="small")
        previewGroup.updateButton = self.glyphLineUpdateButton = Button((-75, 11, -10, 20), "Update", callback=self.updateFeatureFontCallback)

        self.w.pg = previewGroup

        # tab container
        self.w.previewTabs = Tabs((left, topHeight, -0, -0), ["Preview", "Records"], showTabs=False)
        # line view
        self.w.previewTabs[0].lineView = self.glyphLineView = GlyphLineView((0, 0, -0, -0), showPointSizePlacard=True, alternateHighlightColor=AppKit.NSColor.colorWithCalibratedRed_green_blue_alpha_(0, 1, 0, .1))
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
            self.featureFont = None

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
        try:
            self.featureFont = self.featureFontClass(self.font)
        except Exception as e:
            self.featureFont = None
            import traceback
            traceback.print_exc()
            self.showMessage("Compiling Errors:", str(e))
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
        text = str(self.glyphLineInput.get())
        # set into the view
        case = settings["case"]
        if self.featureFont is None:
            self.glyphLineView.set([])
            self.glyphRecordsList.set([])
        else:
            # get the settings
            script = str(settings["script"])
            language = str(settings["language"])
            rightToLeft = bool(settings["rightToLeft"])
            case = str(settings["case"])
            for tag, state in settings["gsub"].items():
                self.featureFont.gsub.setFeatureState(str(tag), bool(state))
            for tag, state in settings["gpos"].items():
                self.featureFont.gpos.setFeatureState(str(tag), bool(state))
            # process
            glyphRecords = self.featureFont.process(text, script=script, langSys=language, rightToLeft=rightToLeft, case=case)
            # set the records
            self.glyphLineView.set(glyphRecords)
            recordData = [dict(Name=record.glyph.name, XP=record.xPlacement, YP=record.yPlacement, XA=record.xAdvance, YA=record.yAdvance, Alternates=", ".join(record.alternates)) for record in glyphRecords]
            self.glyphRecordsList.set(recordData)

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
