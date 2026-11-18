package com.agentflow.util;

import java.io.BufferedReader;
import java.io.IOException;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.List;
import java.util.function.BiConsumer;

/** Incrementally reads UTF-8 SSE events without owning/closing the input stream. */
public final class SseReader {
    private SseReader() {
    }

    public static void read(InputStream input, BiConsumer<String, String> sink) throws IOException {
        BufferedReader reader = new BufferedReader(new InputStreamReader(input, StandardCharsets.UTF_8));
        String event = null;
        List<String> data = new ArrayList<>();
        boolean firstLine = true;
        String line;
        while ((line = reader.readLine()) != null) {
            if (firstLine) {
                if (line.startsWith("\ufeff")) line = line.substring(1);
                firstLine = false;
            }
            if (line.isEmpty()) {
                dispatch(event, data, sink);
                event = null;
                data.clear();
            } else if (!line.startsWith(":")) {
                int colon = line.indexOf(':');
                String field = colon < 0 ? line : line.substring(0, colon);
                String value = colon < 0 ? "" : line.substring(colon + 1);
                if (value.startsWith(" ")) value = value.substring(1);
                if ("event".equals(field)) event = value;
                if ("data".equals(field)) data.add(value);
            }
        }
        // Tolerate a missing final blank line so terminal run events are not lost.
        dispatch(event, data, sink);
    }

    private static void dispatch(String event, List<String> data, BiConsumer<String, String> sink) {
        if (event != null || !data.isEmpty()) {
            sink.accept(event == null || event.isEmpty() ? "message" : event, String.join("\n", data));
        }
    }
}
