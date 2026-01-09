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

import org.apache.lucene.analysis.TokenFilter;
import org.apache.lucene.analysis.TokenStream;
import org.apache.lucene.analysis.tokenattributes.CharTermAttribute;
import org.opensearch.hangul_utils.HanEngUtil;
import org.opensearch.hangul_utils.JamoUtil;

import java.io.IOException;

public class HanToEngFilter extends TokenFilter {

    private final CharTermAttribute charAttr;
    private final JamoUtil jamoUtil;
    private final HanEngUtil hanEngUtil;

    public HanToEngFilter(TokenStream input) {
        super(input);
        jamoUtil = new JamoUtil();
        hanEngUtil = new HanEngUtil();
        charAttr = addAttribute(CharTermAttribute.class);
    }

    @Override
    public final boolean incrementToken() throws IOException {
        if (input.incrementToken()) {
            String hanToEng =
                    hanEngUtil.transformHangulToEnglish(jamoUtil.decompose(charAttr.toString(), true));
            charAttr.setEmpty().append(hanToEng);
            return true;
        }

        return false;
    }
}
