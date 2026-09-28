import java.io.StringReader;
import java.util.ArrayList;
import java.util.List;
import org.apache.lucene.analysis.Tokenizer;
import org.apache.lucene.analysis.tokenattributes.CharTermAttribute;
import example.opensearch.nori.CommerceNoriPlugin;

class PluginCoexistenceCheck {
    static List<String> tokens(Tokenizer tokenizer, String text) throws Exception {
        try (tokenizer) {
            tokenizer.setReader(new StringReader(text));
            var term = tokenizer.addAttribute(CharTermAttribute.class);
            List<String> terms = new ArrayList<>();
            tokenizer.reset();
            while (tokenizer.incrementToken()) {
                terms.add(term.toString());
            }
            tokenizer.end();
            return terms;
        }
    }

    public static void main(String[] arguments) throws Exception {
        var plugin = new CommerceNoriPlugin();
        if (!plugin.getTokenizers().keySet().equals(java.util.Set.of("nori_custom_tokenizer"))) {
            throw new IllegalStateException("Unexpected tokenizer registration");
        }
        var stock = tokens(new org.apache.lucene.analysis.ko.KoreanTokenizer(), "노을빛무선청소기");
        var custom = tokens(new example.opensearch.nori.internal.ko.KoreanTokenizer(), "노을빛무선청소기");
        if (stock.equals(custom) || !custom.equals(List.of("노을빛무선청소기"))) {
            throw new IllegalStateException("Stock and custom dictionaries are not isolated: " + stock + " / " + custom);
        }
        System.out.println("Same-JVM stock/custom dictionary isolation passed: " + stock + " / " + custom);
        var compound = tokens(new example.opensearch.nori.internal.ko.KoreanTokenizer(), "구름결캠핑의자");
        if (!compound.equals(List.of("구름결", "캠핑", "의자"))) {
            throw new IllegalStateException("Relocated compound dictionary failed: " + compound);
        }
        try (var analyzer = new example.opensearch.nori.internal.ko.KoreanAnalyzer()) {
            var stream = analyzer.tokenStream("text", "구름결캠핑의자를 구매했다");
            var term = stream.addAttribute(CharTermAttribute.class);
            List<String> terms = new ArrayList<>();
            stream.reset();
            while (stream.incrementToken()) {
                terms.add(term.toString());
            }
            stream.end();
            stream.close();
            if (!terms.equals(List.of("구름결", "캠핑", "의자", "구매"))) {
                throw new IllegalStateException("Relocated POS/reading filters failed: " + terms);
            }
            System.out.println("Relocated analyzer/filter check passed: " + terms);
        }
    }
}
