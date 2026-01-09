/*
 * Copyright OpenSearch Contributors
 * SPDX-License-Identifier: Apache-2.0
 *
 * The OpenSearch Contributors require contributions made to
 * this file be licensed under the Apache-2.0 license or a
 * compatible open source license.
 *
 */
package org.opensearch.plugin;

import org.opensearch.filters.chosung.ChosungFilterFactory;
import org.opensearch.filters.engtohan.EngToHanFilterFactory;
import org.opensearch.filters.hantoeng.HanToEngFilterFactory;
import org.opensearch.filters.jamo.JamoDecomposeFilterFactory;
import org.opensearch.index.analysis.TokenFilterFactory;
import org.opensearch.plugins.AnalysisPlugin;
import org.opensearch.plugins.Plugin;

import org.opensearch.indices.analysis.AnalysisModule.AnalysisProvider;

import java.util.HashMap;
import java.util.Map;

public class CustomPlugin extends Plugin implements AnalysisPlugin {

    @Override
    public Map<String, AnalysisProvider<TokenFilterFactory>> getTokenFilters() {
        Map<String, AnalysisProvider<TokenFilterFactory>> extra = new HashMap<>();
        extra.put("custom_chosung", ChosungFilterFactory::new);
        extra.put("custom_jamo", JamoDecomposeFilterFactory::new);
        extra.put("custom_engtohan", EngToHanFilterFactory::new);
        extra.put("custom_hantoeng", HanToEngFilterFactory::new);

        return extra;
    }
}
