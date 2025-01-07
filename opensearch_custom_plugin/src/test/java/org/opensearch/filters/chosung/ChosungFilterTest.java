/*
 * Copyright OpenSearch Contributors
 * SPDX-License-Identifier: Apache-2.0
 *
 * The OpenSearch Contributors require contributions made to
 * this file be licensed under the Apache-2.0 license or a
 * compatible open source license.
 *
 */
package org.opensearch.filters.chosung;

import static org.junit.jupiter.api.Assertions.assertEquals;
import java.io.IOException;
import java.util.ArrayList;
import java.util.List;

import org.apache.logging.log4j.LogManager;
import org.apache.logging.log4j.Logger;
import org.apache.lucene.analysis.Analyzer;
import org.apache.lucene.analysis.TokenStream;
import org.apache.lucene.analysis.Tokenizer;
import org.apache.lucene.analysis.core.KeywordTokenizer;
import org.apache.lucene.analysis.tokenattributes.CharTermAttribute;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

public class ChosungFilterTest {

    private Analyzer analyzer;
    private static final Logger logger = LogManager.getLogger(ChosungFilterTest.class);

    private String getChosungString(String text) throws IOException {
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
                TokenStream tokenFilter = new ChosungFilter(tokenizer);
                return new TokenStreamComponents(tokenizer, tokenFilter);
            }
        };
    }

    @Test
    void testOnlyHangul() throws IOException {
        assertEquals("ㅇㅍ ㅅㅊ", getChosungString("오픈 서치"));
    }

    @Test
    void testContainsEnglish() throws IOException {
        assertEquals("ㅇㅍ search", getChosungString("오픈 search"));
    }

    @Test
    void testContainsSpecialCharacters() throws IOException {
        assertEquals("([]ㅇㅍ!@#ㅅㅊ", getChosungString("([]오픈!@#서치"));
    }

    @Test
    void testReturnOriginalJamoIfContainsJamo() throws IOException {
        assertEquals("ㅇㅍㅡㄴ ㅅㅓㅊ", getChosungString("오ㅍ-ㄴ ㅅㅓ치"));
    }

    @Test
    void testContainsStacking() throws IOException {
        assertEquals("ㄱㅈㄷ", getChosungString("값지다"));
        assertEquals("ㅇㄷ", getChosungString("앉다"));
    }
}