package example.opensearch.nori;

import java.io.IOException;
import java.io.StringReader;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import org.apache.lucene.analysis.Analyzer;
import org.apache.lucene.analysis.TokenStream;
import org.apache.lucene.analysis.Tokenizer;
import org.apache.lucene.analysis.ko.KoreanAnalyzer;
import org.apache.lucene.analysis.ko.KoreanNumberFilter;
import org.apache.lucene.analysis.ko.KoreanPartOfSpeechStopFilter;
import org.apache.lucene.analysis.ko.KoreanReadingFormFilter;
import org.apache.lucene.analysis.ko.KoreanTokenizer;
import org.apache.lucene.analysis.ko.POS;
import org.apache.lucene.analysis.ko.dict.UserDictionary;
import org.opensearch.common.settings.Settings;
import org.opensearch.env.Environment;
import org.opensearch.index.IndexSettings;
import org.opensearch.index.analysis.AbstractIndexAnalyzerProvider;
import org.opensearch.index.analysis.AbstractTokenFilterFactory;
import org.opensearch.index.analysis.AbstractTokenizerFactory;
import org.opensearch.index.analysis.Analysis;
import org.opensearch.index.analysis.AnalyzerProvider;
import org.opensearch.index.analysis.TokenFilterFactory;
import org.opensearch.index.analysis.TokenizerFactory;
import org.opensearch.indices.analysis.AnalysisModule.AnalysisProvider;
import org.opensearch.plugins.AnalysisPlugin;
import org.opensearch.plugins.Plugin;

public final class CommerceNoriPlugin extends Plugin implements AnalysisPlugin {
    @Override
    public Map<String, AnalysisProvider<TokenizerFactory>> getTokenizers() {
        return Map.of("nori_custom_tokenizer", CommerceTokenizerFactory::new);
    }

    @Override
    public Map<String, AnalysisProvider<AnalyzerProvider<? extends Analyzer>>> getAnalyzers() {
        return Map.of("nori_custom", CommerceAnalyzerProvider::new);
    }

    @Override
    public Map<String, AnalysisProvider<TokenFilterFactory>> getTokenFilters() {
        return Map.of(
            "nori_custom_part_of_speech", (index, environment, name, settings) -> new CommerceFilterFactory(index, name, settings, "pos"),
            "nori_custom_readingform", (index, environment, name, settings) -> new CommerceFilterFactory(index, name, settings, "reading"),
            "nori_custom_number", (index, environment, name, settings) -> new CommerceFilterFactory(index, name, settings, "number")
        );
    }

    private static UserDictionary userDictionary(Environment environment, Settings settings) throws IOException {
        if (settings.get("user_dictionary") != null && settings.get("user_dictionary_rules") != null) {
            throw new IllegalArgumentException("Use either user_dictionary or user_dictionary_rules, not both");
        }
        List<String> rules = Analysis.parseWordList(environment, settings, "user_dictionary", "user_dictionary_rules", value -> value);
        if (rules == null || rules.isEmpty()) {
            return null;
        }
        try (var reader = new StringReader(String.join("\n", rules))) {
            return UserDictionary.open(reader);
        }
    }

    private static KoreanTokenizer.DecompoundMode mode(Settings settings) {
        return KoreanTokenizer.DecompoundMode.valueOf(settings.get("decompound_mode", "discard").toUpperCase(java.util.Locale.ROOT));
    }

    private static Set<POS.Tag> stopTags(Settings settings) {
        if (settings.getAsList("stoptags", null) == null) {
            return KoreanPartOfSpeechStopFilter.DEFAULT_STOP_TAGS;
        }
        Set<POS.Tag> result = new HashSet<>();
        for (String tag : settings.getAsList("stoptags")) {
            result.add(POS.resolveTag(tag));
        }
        return result;
    }

    private static final class CommerceTokenizerFactory extends AbstractTokenizerFactory {
        private final UserDictionary dictionary;
        private final KoreanTokenizer.DecompoundMode decompoundMode;
        private final boolean discardPunctuation;

        CommerceTokenizerFactory(IndexSettings index, Environment environment, String name, Settings settings) throws IOException {
            super(index, settings, name);
            dictionary = userDictionary(environment, settings);
            decompoundMode = mode(settings);
            discardPunctuation = settings.getAsBoolean("discard_punctuation", true);
        }

        @Override
        public Tokenizer create() {
            return new KoreanTokenizer(KoreanTokenizer.DEFAULT_TOKEN_ATTRIBUTE_FACTORY, dictionary, decompoundMode, false, discardPunctuation);
        }
    }

    private static final class CommerceAnalyzerProvider extends AbstractIndexAnalyzerProvider<KoreanAnalyzer> {
        private final KoreanAnalyzer analyzer;

        CommerceAnalyzerProvider(IndexSettings index, Environment environment, String name, Settings settings) throws IOException {
            super(index, name, settings);
            analyzer = new KoreanAnalyzer(userDictionary(environment, settings), mode(settings), stopTags(settings), false);
        }

        @Override
        public KoreanAnalyzer get() {
            return analyzer;
        }
    }

    private static final class CommerceFilterFactory extends AbstractTokenFilterFactory {
        private final String kind;
        private final Set<POS.Tag> tags;

        CommerceFilterFactory(IndexSettings index, String name, Settings settings, String kind) {
            super(index, name, settings);
            this.kind = kind;
            tags = stopTags(settings);
        }

        @Override
        public TokenStream create(TokenStream stream) {
            return switch (kind) {
                case "pos" -> new KoreanPartOfSpeechStopFilter(stream, tags);
                case "reading" -> new KoreanReadingFormFilter(stream);
                case "number" -> new KoreanNumberFilter(stream);
                default -> throw new IllegalStateException("Unexpected filter kind");
            };
        }
    }
}
