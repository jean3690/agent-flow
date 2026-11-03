package com.agentflow.util;

import org.junit.jupiter.api.Test;

import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

class KnowledgeScorerTest {

    @Test
    void gramCountsNormalizesAndCountsChineseBigrams() {
        var grams = KnowledgeScorer.gramCounts("退款多久到账！");
        assertEquals(5, grams.size());
        assertEquals(1, grams.get("退款"));
        assertEquals(1, grams.get("到账"));
    }

    @Test
    void lexicalScorePrefersChunkContainingQueryTerms() {
        var query = KnowledgeScorer.gramCounts("退款多久到账");
        var hit = KnowledgeScorer.gramCounts("退款会在审核通过后 3 个工作日内原路退回，具体到账时间以银行为准。");
        var miss = KnowledgeScorer.gramCounts("会员等级规则：普通会员累计消费满 500 元升级为银卡会员。");

        var df = Map.of("退款", 1, "到账", 1);
        double ceiling = KnowledgeScorer.lexicalCeiling(query, 2, df);

        double hitScore = KnowledgeScorer.lexicalScore(query, hit, 2, df, ceiling);
        double missScore = KnowledgeScorer.lexicalScore(query, miss, 2, df, ceiling);
        assertTrue(hitScore > missScore, "hit=" + hitScore + " miss=" + missScore);
        assertTrue(hitScore > 0 && hitScore <= 1);
        assertEquals(0, missScore);
    }

    @Test
    void cosineOfIdenticalVectorsIsOne() {
        assertEquals(1.0, KnowledgeScorer.cosine(new double[]{0.5, 0.5}, new double[]{0.5, 0.5}), 1e-9);
        assertEquals(0.0, KnowledgeScorer.cosine(new double[]{1, 0}, new double[]{0, 1}), 1e-9);
    }

    @Test
    void hybridBlendsCosineAndLexical() {
        double blended = KnowledgeScorer.hybrid(0.8, 0.5);
        assertEquals(0.7 * 0.8 + 0.3 * 0.5, blended, 1e-9);
        // 无向量时退化为纯词法
        assertEquals(0.5, KnowledgeScorer.hybrid(0, 0.5), 1e-9);
    }
}
