from fontTools.ttLib import TTFont
from fontTools.fontBuilder import FontBuilder

from featurePreview import FeatureFont, FeatureTester


class BinaryFeatureFont(FeatureFont):

    def buildBinaryFont(self):
        font = self.font
        path = font.lib.get("com.typemytype.robofont.binarySource")
        self.source = TTFont(path)
        ff = FontBuilder(font=self.source)
        if self.cmap:
            ff.setupCharacterMap(self.cmap)
        with open(path, "rb") as f:
            self._data = f.read()


class BinaryFeatureTester(FeatureTester):

    featureFontClass = BinaryFeatureFont


if __name__ is "__main__":
    BinaryFeatureTester(font=OpenFont(showInterface=False))
