package com.agentflow.util;

import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;

import java.io.ByteArrayInputStream;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;

class SseReaderTest {
    @ParameterizedTest
    @ValueSource(strings = {"\n", "\r\n", "\r"})
    void readsMultilineDataDefaultEventAndComments(String newline) throws Exception {
        String body = String.join(newline, "\ufeff: heartbeat", "", "data: {\"text\":", "data: \"你好\"}", "", "");
        assertThat(read(body)).containsExactly(List.of("message", "{\"text\":\n\"你好\"}"));
    }

    @ParameterizedTest
    @ValueSource(strings = {"", "\n", "\r\n"})
    void retainsTerminalEventWithoutBlankSeparator(String suffix) throws Exception {
        assertThat(read("event: run_finished\ndata: {}" + suffix))
                .containsExactly(List.of("run_finished", "{}"));
    }

    @Test
    void preservesWhitespaceAndResetsEventName() throws Exception {
        assertThat(read("event: node_token\ndata:  value  \n\ndata: {}\n\n"))
                .containsExactly(List.of("node_token", " value  "), List.of("message", "{}"));
    }

    private List<List<String>> read(String text) throws Exception {
        List<List<String>> result = new ArrayList<>();
        SseReader.read(new ByteArrayInputStream(text.getBytes(StandardCharsets.UTF_8)),
                (name, data) -> result.add(List.of(name, data)));
        return result;
    }
}
