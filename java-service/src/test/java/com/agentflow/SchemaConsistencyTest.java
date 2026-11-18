package com.agentflow;

import com.baomidou.mybatisplus.annotation.TableName;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.config.BeanDefinition;
import org.springframework.context.annotation.ClassPathScanningCandidateComponentProvider;
import org.springframework.core.type.filter.AnnotationTypeFilter;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.LinkedHashSet;
import java.util.Set;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * 保证实体表名与两套建表脚本保持一致。
 *
 * <p>H2 的 {@code h2-schema.sql} 用于本地开发，{@code docs/schema.mysql.sql} 用于生产。
 * 任何新增实体都必须同时补两份脚本，否则 MySQL 部署会在运行期才暴露缺表问题。
 */
class SchemaConsistencyTest {

    private static final String ENTITY_PACKAGE = "com.agentflow.entity";

    @Test
    void everyEntityTableExistsInBothSchemas() throws IOException {
        Set<String> tables = entityTables();
        assertThat(tables).isNotEmpty();

        String h2 = readClasspath("h2-schema.sql");
        String mysql = readMysqlSchema();

        for (String table : tables) {
            String pattern = "(?i)CREATE TABLE IF NOT EXISTS\\s+`?" + table + "`?\\b";
            assertThat(h2)
                    .as("h2-schema.sql 缺少实体表 %s", table)
                    .containsPattern(pattern);
            assertThat(mysql)
                    .as("docs/schema.mysql.sql 缺少实体表 %s", table)
                    .containsPattern(pattern);
        }
    }

    private Set<String> entityTables() {
        ClassPathScanningCandidateComponentProvider scanner =
                new ClassPathScanningCandidateComponentProvider(false);
        scanner.addIncludeFilter(new AnnotationTypeFilter(TableName.class));

        Set<String> tables = new LinkedHashSet<>();
        for (BeanDefinition candidate : scanner.findCandidateComponents(ENTITY_PACKAGE)) {
            try {
                Class<?> type = Class.forName(candidate.getBeanClassName());
                TableName annotation = type.getAnnotation(TableName.class);
                if (annotation != null && !annotation.value().isBlank()) {
                    tables.add(annotation.value());
                }
            } catch (ClassNotFoundException ex) {
                throw new IllegalStateException("无法加载实体类: " + candidate.getBeanClassName(), ex);
            }
        }
        return tables;
    }

    private String readClasspath(String name) throws IOException {
        try (var stream = getClass().getClassLoader().getResourceAsStream(name)) {
            if (stream == null) {
                throw new IOException("classpath resource not found: " + name);
            }
            return new String(stream.readAllBytes(), StandardCharsets.UTF_8);
        }
    }

    private String readMysqlSchema() throws IOException {
        for (Path path : new Path[]{Path.of("../docs/schema.mysql.sql"), Path.of("docs/schema.mysql.sql")}) {
            if (Files.isRegularFile(path)) {
                return Files.readString(path, StandardCharsets.UTF_8);
            }
        }
        throw new IOException("docs/schema.mysql.sql not found; run tests from java-service or repo root");
    }
}
