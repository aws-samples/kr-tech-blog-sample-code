import java.io.StringReader;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.List;
import org.apache.lucene.analysis.ko.KoreanTokenizer;
import org.apache.lucene.analysis.ko.dict.UserDictionary;
import org.apache.lucene.analysis.ko.tokenattributes.PartOfSpeechAttribute;
import org.apache.lucene.analysis.tokenattributes.CharTermAttribute;
import org.apache.lucene.analysis.tokenattributes.OffsetAttribute;
import org.apache.lucene.analysis.tokenattributes.PositionIncrementAttribute;
import org.apache.lucene.analysis.tokenattributes.PositionLengthAttribute;

class NoriCompare {
    static String quote(String value) {
        return "\"" + value.replace("\\", "\\\\").replace("\"", "\\\"") + "\"";
    }

    public static void main(String[] arguments) throws Exception {
        String variant = arguments[0];
        UserDictionary dictionary = null;
        if (arguments.length > 1) {
            try (var reader = Files.newBufferedReader(Path.of(arguments[1]))) {
                dictionary = UserDictionary.open(reader);
            }
        }
        List<String> texts = List.of("노을빛무선청소기", "구름결캠핑의자", "별하늘진공텀블러", "초록별접이식선반",
            "노을빛무선청소기에서 먼지를 제거한다", "구름결캠핑의자를 구매했다", "별하늘진공텀블러는 가볍다",
            "초록별접이식선반을 설치했다", "아버지가 가방에 들어가신다");
        for (String text : texts) {
            for (var mode : KoreanTokenizer.DecompoundMode.values()) {
                List<String> tokens = new ArrayList<>();
                try (var tokenizer = new KoreanTokenizer(KoreanTokenizer.DEFAULT_TOKEN_ATTRIBUTE_FACTORY,
                        dictionary, mode, false, true)) {
                    tokenizer.setReader(new StringReader(text));
                    var term = tokenizer.addAttribute(CharTermAttribute.class);
                    var pos = tokenizer.addAttribute(PartOfSpeechAttribute.class);
                    var offset = tokenizer.addAttribute(OffsetAttribute.class);
                    var increment = tokenizer.addAttribute(PositionIncrementAttribute.class);
                    var length = tokenizer.addAttribute(PositionLengthAttribute.class);
                    tokenizer.reset();
                    int position = -1;
                    while (tokenizer.incrementToken()) {
                        position += increment.getPositionIncrement();
                        tokens.add("{\"token\":" + quote(term.toString()) + ",\"pos\":" + quote(pos.getLeftPOS().name())
                            + ",\"start\":" + offset.startOffset() + ",\"end\":" + offset.endOffset()
                            + ",\"position\":" + position + ",\"positionLength\":" + length.getPositionLength() + "}");
                    }
                    tokenizer.end();
                }
                System.out.println("{\"variant\":" + quote(variant) + ",\"text\":" + quote(text)
                    + ",\"mode\":" + quote(mode.name().toLowerCase()) + ",\"tokens\":[" + String.join(",", tokens) + "]}");
            }
        }
    }
}
