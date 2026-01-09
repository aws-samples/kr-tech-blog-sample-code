/*
 * Copyright OpenSearch Contributors
 * SPDX-License-Identifier: Apache-2.0
 *
 * The OpenSearch Contributors require contributions made to
 * this file be licensed under the Apache-2.0 license or a
 * compatible open source license.
 *
 */
package org.opensearch.filters.hantoeng;

import static org.junit.jupiter.api.Assertions.assertEquals;
import java.io.IOException;
import java.util.ArrayList;
import java.util.List;
import org.apache.lucene.analysis.Analyzer;
import org.apache.lucene.analysis.TokenStream;
import org.apache.lucene.analysis.Tokenizer;
import org.apache.lucene.analysis.core.KeywordTokenizer;
import org.apache.lucene.analysis.tokenattributes.CharTermAttribute;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.apache.logging.log4j.LogManager;
import org.apache.logging.log4j.Logger;

public class HanToEngFilterTest {

    private static final Logger logger = LogManager.getLogger(HanToEngFilterTest.class);

    private Analyzer analyzer;

    private String getHangulToEnglish(String text) throws IOException {
        TokenStream stream = analyzer.tokenStream("field", text);

        CharTermAttribute charAttr = stream.addAttribute(CharTermAttribute.class);

        stream.reset();

        List<String> tokenStrs = new ArrayList<>();
        while (stream.incrementToken()) {
            tokenStrs.add(charAttr.toString());
        }
        stream.close();

        String result = String.join(" ", tokenStrs);
        logger.debug(result);

        return result;
    }

    @BeforeEach
    public void setup() {
        analyzer = new Analyzer(Analyzer.PER_FIELD_REUSE_STRATEGY) {
            @Override
            protected TokenStreamComponents createComponents(String fieldName) {
                Tokenizer tokenizer = new KeywordTokenizer();
                TokenStream tokenFilter = new HanToEngFilter(tokenizer);
                return new TokenStreamComponents(tokenizer, tokenFilter);
            }
        };
    }

    @Test
    void testOnlyHangul() throws IOException {
        assertEquals("opensearch", getHangulToEnglish("ㅐㅔ둔ㄷㅁㄱ초"));
    }

    @Test
    void testContainsEnglish() throws IOException {
        assertEquals("amazon.com", getHangulToEnglish("믐캐ㅜ.채ㅡ"));
    }

    @Test
    void testContainsSpecialCharacters() throws IOException {
        assertEquals("opensearch!@#$%^&&**((", getHangulToEnglish("ㅐㅔ둔ㄷㅁㄱ초!@#$%^&&**(("));
    }

    @Test
    void testContainsStacking() throws IOException {
        assertEquals("sword", getHangulToEnglish("ㄴ잭ㅇ"));
    }
}