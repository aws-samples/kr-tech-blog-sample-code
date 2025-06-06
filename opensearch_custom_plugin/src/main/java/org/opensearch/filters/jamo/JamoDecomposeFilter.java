/*
 * Copyright OpenSearch Contributors
 * SPDX-License-Identifier: Apache-2.0
 *
 * The OpenSearch Contributors require contributions made to
 * this file be licensed under the Apache-2.0 license or a
 * compatible open source license.
 *
 */
package org.opensearch.filters.jamo;

import org.apache.lucene.analysis.TokenFilter;
import org.apache.lucene.analysis.TokenStream;
import org.apache.lucene.analysis.tokenattributes.CharTermAttribute;
import org.opensearch.hangul_utils.JamoUtil;

import java.io.IOException;

public class JamoDecomposeFilter extends TokenFilter {

    private final CharTermAttribute charAttr;
    private final JamoUtil jamoUtil;

    public JamoDecomposeFilter(TokenStream input) {
        super(input);
        jamoUtil = new JamoUtil();
        charAttr = addAttribute(CharTermAttribute.class);
    }

    @Override
    public final boolean incrementToken() throws IOException {

        if (input.incrementToken()) {
            String jamo = jamoUtil.decompose(charAttr.toString(), true);
            charAttr.setEmpty().append(jamo);
            return true;
        }

        return false;
    }
}
