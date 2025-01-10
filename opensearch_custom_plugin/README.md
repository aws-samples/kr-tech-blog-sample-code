# OpenSearch-Plugin-example

Reference blog post - [My first steps in OpenSearch Plugins](https://opensearch.org/blog/technical-posts/2021/06/my-first-steps-in-opensearch-plugins/)

Reference Source Code
- [OpenSearch Plugins](https://github.com/opensearch-project/opensearch-plugins/tree/main)
- [OpenSearch plugin template java](https://github.com/opensearch-project/opensearch-plugin-template-java)
- [hanhinsam](https://github.com/yainage90/hanhinsam)


## Build ans Install

#### Buile

Project clone and move root directory

``` shell
./gradlew clean build
```

#### Check plugin artifact

build/distributions/opensearch-plugin-example-1.0.0.zip

1. jar file
2. LICENSE.txt
3. NOTICE.txt
4. plugin-descriptor.properties



## Plugin Test

### 1) Typo correction
If you plan to correct typos when searching for a specific field, create an additional field to index the string with the letter separation. The field is of type `text` because it needs to be analyzed. Create an analyzer to analyze this field and apply `jamo_filter` to the filter. The Term Suggest API enables typo correction through this field.

``` javascript
//Create Index
PUT /spell_test
{
  "settings": {
    "number_of_shards": 1,
    "number_of_replicas": 0,
    "index.max_ngram_diff": 10,
    "analysis": {
      "analyzer": {
        "jamo_analyzer": {
          "type": "custom",
          "tokenizer": "standard",
          "filter": [
            "lowercase",
            "custom_jamo"
          ]
        }
      }
    }
  },
  "mappings": {
    "properties": {
      "name": {
        "type": "keyword",
        "copy_to": ["name_jamo"]
      },
      "name_jamo": {
        "type": "text",
        "analyzer": "jamo_analyzer"
      }
    }
  }
}

//Indexing
POST /_bulk
{ "index" : { "_index" : "spell_test", "_id" : "1" } }
{ "name" : "손오공" }
{ "index" : { "_index" : "spell_test", "_id" : "2" } }
{ "name" : "오픈서치" }
{ "index" : { "_index" : "spell_test", "_id" : "3" } }
{ "name" : "아메리카노" }

//Test
POST /spell_test/_search
{
  "suggest": {
    "name_suggest": {
      "text": "아메리치노",
      "term": {
        "field": "name_jamo",
        "max_edits": 2
      }
    }
  }
}
```

``` javascript
//Result
{
  "took" : 7,
  "timed_out" : false,
  "_shards" : {
    "total" : 1,
    "successful" : 1,
    "skipped" : 0,
    "failed" : 0
  },
  "hits" : {
    "total" : {
      "value" : 0,
      "relation" : "eq"
    },
    "max_score" : null,
    "hits" : [ ]
  },
  "suggest" : {
    "name_suggest" : [
      {
        "text" : "ㅇㅏㅁㅔㄹㅣㅊㅣㄴㅗ",
        "offset" : 0,
        "length" : 5,
        "options" : [
          {
            "text" : "ㅇㅏㅁㅔㄹㅣㅋㅏㄴㅗ",
            "score" : 0.8,
            "freq" : 1
          }
        ]
      }
    ]
  }
}
```

### 2) Correct typos in Korean/English conversions.

Create an additional field for indexing each of the converted strings. These fields are of type `text` because they need to be analyzed. Create analyzers with a han/eng filter applied and specify each analyzer as the `search_analyzer` of the han/eng converted field.

``` javascript
//Create Index
PUT /haneng_test
{
  "settings": {
    "number_of_shards": 1,
    "number_of_replicas": 0,
    "index.max_ngram_diff": 10,
    "analysis": {
      "analyzer": {
        "engtohan_analyzer": {
          "type": "custom",
          "tokenizer": "standard",
          "filter": [
            "lowercase",
            "custom_engtohan"
          ]
        },
        "hantoeng_analyzer": {
          "type": "custom",
          "tokenizer": "standard",
          "filter": [
            "lowercase",
            "custom_hantoeng"
          ]
        }
      }
    }
  },
  "mappings": {
    "properties": {
      "name": {
        "type": "keyword",
        "copy_to": ["name_hantoeng", "name_engtohan"]
      },
      "name_hantoeng": {
        "type": "text",
        "search_analyzer": "hantoeng_analyzer"
      },
      "name_engtohan": {
        "type": "text",
        "search_analyzer": "engtohan_analyzer"
      }
    }
  }
}

//Indexing
POST /_bulk
{ "index" : { "_index" : "haneng_test", "_id" : "1" } }
{ "name" : "손오공" }
{ "index" : { "_index" : "haneng_test", "_id" : "2" } }
{ "name" : "Open" }
{ "index" : { "_index" : "haneng_test", "_id" : "3" } }
{ "name" : "아메리카노" }

//hantoeng Test
POST /haneng_test/_search
{
  "query": {
    "match": {
      "name_hantoeng": "ㅐㅔ두"
    }
  }
}

//engtohan Test
POST /haneng_test/_search
{
  "query": {
    "match": {
      "name_engtohan": "thsdhrhd"
    }
  }
}
```

``` javascript
//Result
{
  "took" : 2,
  "timed_out" : false,
  "_shards" : {
    "total" : 1,
    "successful" : 1,
    "skipped" : 0,
    "failed" : 0
  },
  "hits" : {
    "total" : {
      "value" : 1,
      "relation" : "eq"
    },
    "max_score" : 0.9808291,
    "hits" : [
      {
        "_index" : "haneng_test",
        "_type" : "_doc",
        "_id" : "2",
        "_score" : 0.9808291,
        "_source" : {
          "name" : "open"
        }
      }
    ]
  }
}

//English to Koreans conversion typo correction search test results
{
  "took" : 2,
  "timed_out" : false,
  "_shards" : {
    "total" : 1,
    "successful" : 1,
    "skipped" : 0,
    "failed" : 0
  },
  "hits" : {
    "total" : {
      "value" : 1,
      "relation" : "eq"
    },
    "max_score" : 0.9808291,
    "hits" : [
      {
        "_index" : "haneng_test",
        "_type" : "_doc",
        "_id" : "1",
        "_score" : 0.9808291,
        "_source" : {
          "name" : "손오공"
        }
      }
    ]
  }
}
```

### 3) Search for chosung

Create an analyzer with an additional field of type `text` to index strings with a separated initialization and a filter for initialization. You can then search for initialization via that field.


``` javascript
//Create Index
PUT /chosung_test
{
  "settings": {
    "number_of_shards": 1,
    "number_of_replicas": 0,
    "index.max_ngram_diff": 10,
    "analysis": {
      "analyzer": {
        "chosung_analyzer": {
          "type": "custom",
          "tokenizer": "standard",
          "filter": [
            "lowercase",
            "custom_chosung"
          ]
        }
      }
    }
  },
  "mappings": {
    "properties": {
      "name": {
        "type": "keyword",
        "copy_to": ["name_chosung"]
      },
      "name_chosung": {
        "type": "text",
        "analyzer": "chosung_analyzer"
      }
    }
  }
}

//Indexing
POST /_bulk
{ "index" : { "_index" : "chosung_test", "_id" : "2" } }
{ "name" : "오픈서치" }
{ "index" : { "_index" : "chosung_test", "_id" : "3" } }
{ "name" : "아메리카노" }

//Test
POST /chosung_test/_search
{
  "query": {
    "match": {
      "name_chosung": "ㅇㅍㅅㅊ"
    }
  }
}
```

``` javascript
//Result
{
  "took" : 1,
  "timed_out" : false,
  "_shards" : {
    "total" : 1,
    "successful" : 1,
    "skipped" : 0,
    "failed" : 0
  },
  "hits" : {
    "total" : {
      "value" : 1,
      "relation" : "eq"
    },
    "max_score" : 0.6931471,
    "hits" : [
      {
        "_index" : "chosung_test",
        "_type" : "_doc",
        "_id" : "2",
        "_score" : 0.6931471,
        "_source" : {
          "name" : "오픈서치"
        }
      }
    ]
  }
}
```

### 4) Autocomplete

Create an additional field of type `text` for autocomplete. The index analyzer uses an ngram tokenizer to ensure that substrings are indexed together. The search analyzer only applies `jamo_filter`. The additional fields created for further analysis will allow searching via partial matching, which will allow the service to implement autocomplete functionality.

``` javascript
//Create Index
PUT /ac_test
{
  "settings": {
    "number_of_shards": 1,
    "number_of_replicas": 0,
    "index.max_ngram_diff": 30,
    "analysis": {
      "filter": {
        "ngram_filter": {
          "type": "ngram",
          "min_gram": 1,
          "max_gram": 20
        }
      },
      "analyzer": {
        "jamo_analyzer": {
          "type": "custom",
          "tokenizer": "standard",
          "filter": [
            "lowercase",
            "custom_jamo"
          ]
        },
        "ngram_jamo_analyzer": {
          "type": "custom",
          "tokenizer": "standard",
          "filter": [
            "lowercase",
            "custom_jamo",
            "ngram_filter"
          ]
        }
      }
    }
  },
  "mappings": {
    "properties": {
      "name": {
        "type": "keyword",
        "copy_to": "name_ngram"
      },
      "name_ngram": {
        "type": "text",
        "analyzer": "ngram_jamo_analyzer",
        "search_analyzer": "jamo_analyzer"
      }
    }
  }
}

//Indexing
POST /_bulk
{ "index" : { "_index" : "ac_test", "_id" : "1" } }
{ "name" : "손오공" }
{ "index" : { "_index" : "ac_test", "_id" : "2" } }
{ "name" : "open" }
{ "index" : { "_index" : "ac_test", "_id" : "3" } }
{ "name" : "아메리카노" }

//Autocomplete Test
POST /ac_test/_search
{
  "query": {
    "match": {
      "name_ngram": "아멜"
    }
  }
}
```

``` javascript
//Result
{
  "took" : 1,
  "timed_out" : false,
  "_shards" : {
    "total" : 1,
    "successful" : 1,
    "skipped" : 0,
    "failed" : 0
  },
  "hits" : {
    "total" : {
      "value" : 1,
      "relation" : "eq"
    },
    "max_score" : 1.631392,
    "hits" : [
      {
        "_index" : "ac_test",
        "_type" : "_doc",
        "_id" : "3",
        "_score" : 1.631392,
        "_source" : {
          "name" : "아메리카노"
        }
      }
    ]
  }
}
```
