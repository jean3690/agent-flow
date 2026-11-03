package com.agentflow.util;

import java.util.HashMap;
import java.util.Map;

/**
 * 知识检索打分：字符 bigram + IDF 的词法覆盖率，以及向量余弦相似度。
 * 纯函数、无状态，便于单测。
 */
public final class KnowledgeScorer {

    private KnowledgeScorer() {
    }

    public static Map<String, Integer> gramCounts(String text) {
        Map<String, Integer> grams = new HashMap<>();
        String normalized = normalize(text);
        if (normalized.length() < 2) {
            if (!normalized.isEmpty()) {
                grams.put(normalized, 1);
            }
            return grams;
        }
        for (int index = 0; index < normalized.length() - 1; index++) {
            grams.merge(normalized.substring(index, index + 2), 1, Integer::sum);
        }
        return grams;
    }

    public static String normalize(String text) {
        if (text == null) {
            return "";
        }
        StringBuilder buffer = new StringBuilder();
        for (char current : text.toLowerCase().toCharArray()) {
            if (Character.isLetterOrDigit(current)) {
                buffer.append(current);
            }
        }
        return buffer.toString();
    }

    public static double idf(String gram, int chunkCount, Map<String, Integer> documentFrequency) {
        int frequency = documentFrequency.getOrDefault(gram, 0);
        return Math.log((chunkCount + 1.0) / (frequency + 1.0)) + 1.0;
    }

    public static double lexicalCeiling(Map<String, Integer> queryGrams, int chunkCount, Map<String, Integer> documentFrequency) {
        return queryGrams.keySet().stream()
                .mapToDouble(gram -> idf(gram, chunkCount, documentFrequency) * 3)
                .sum();
    }

    /**
     * 词法得分：查询 bigram 的 IDF 加权覆盖（词频做饱和处理，避免长分片靠重复词刷分），归一化到 0-1。
     */
    public static double lexicalScore(Map<String, Integer> queryGrams, Map<String, Integer> chunkGrams,
                                      int chunkCount, Map<String, Integer> documentFrequency, double ceiling) {
        if (queryGrams.isEmpty() || chunkGrams.isEmpty() || ceiling <= 0) {
            return 0;
        }
        double score = 0;
        for (Map.Entry<String, Integer> entry : queryGrams.entrySet()) {
            Integer frequency = chunkGrams.get(entry.getKey());
            if (frequency == null) {
                continue;
            }
            score += idf(entry.getKey(), chunkCount, documentFrequency) * Math.min(frequency, 3);
        }
        return score / ceiling;
    }

    public static double cosine(double[] left, double[] right) {
        if (left == null || right == null || left.length != right.length) {
            return 0;
        }
        double dot = 0;
        double leftNorm = 0;
        double rightNorm = 0;
        for (int index = 0; index < left.length; index++) {
            dot += left[index] * right[index];
            leftNorm += left[index] * left[index];
            rightNorm += right[index] * right[index];
        }
        if (leftNorm == 0 || rightNorm == 0) {
            return 0;
        }
        return dot / (Math.sqrt(leftNorm) * Math.sqrt(rightNorm));
    }

    /** 混合重排：向量相似为主、词法覆盖为辅；无向量时退化为纯词法。 */
    public static double hybrid(double cosine, double lexical) {
        if (cosine <= 0) {
            return lexical;
        }
        return 0.7 * cosine + 0.3 * lexical;
    }
}
