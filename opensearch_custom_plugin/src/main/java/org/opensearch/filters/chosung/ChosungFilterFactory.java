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

import org.apache.lucene.analysis.TokenStream;
import org.opensearch.common.settings.Settings;
import org.opensearch.env.Environment;
import org.opensearch.index.IndexSettings;
import org.opensearch.index.analysis.AbstractTokenFilterFactory;

public class ChosungFilterFactory extends AbstractTokenFilterFactory {

    public ChosungFilterFactory(IndexSettings indexSettings, Environment env, String name,
                                Settings settings) {
        super(indexSettings, name, settings);
    }

    @Override
    public TokenStream create(TokenStream tokenStream) {
        return new ChosungFilter(tokenStream);
    }
}
