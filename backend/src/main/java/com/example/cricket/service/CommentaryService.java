package com.example.cricket.service;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.ai.chat.client.ChatClient;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;

import java.util.concurrent.CompletableFuture;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.TimeoutException;

/**
 * OPTIONAL AI commentary via Spring AI + local Ollama.
 * Ported from the original livecricket project and hardened:
 *  - disabled by default (cricket.commentary.enabled=false); when disabled or
 *    when Ollama is unreachable, generate() returns null and the calling API
 *    keeps working - commentary never breaks score updates.
 */
@Service
public class CommentaryService {

    private static final Logger log = LoggerFactory.getLogger(CommentaryService.class);

    private final ChatClient chatClient;
    private final boolean enabled;
    private final long timeoutMs;

    public CommentaryService(ChatClient.Builder builder,
                             @Value("${cricket.commentary.enabled:false}") boolean enabled,
                             @Value("${cricket.commentary.timeout-ms:5000}") long timeoutMs) {
        this.chatClient = builder.build();
        this.enabled = enabled;
        this.timeoutMs = timeoutMs;
    }

    /** Returns a one-line commentary, or null when disabled/unavailable. */
    public String generate(String scoreSummary) {
        if (!enabled) {
            return null;
        }
        try {
            return CompletableFuture
                    .supplyAsync(() -> chatClient.prompt()
                            .user(prompt(scoreSummary))
                            .call()
                            .content())
                    .get(timeoutMs, TimeUnit.MILLISECONDS);
        } catch (TimeoutException e) {
            log.warn("AI commentary timed out after {} ms", timeoutMs);
            return null;
        } catch (Exception e) {
            log.warn("AI commentary unavailable (is Ollama running?): {}", e.getMessage());
            return null;
        }
    }

    private static String prompt(String score) {
        return """
                Generate ONE short professional live cricket commentary line.

                Style:
                - Like Cricbuzz or Cricinfo
                - Maximum 20 words
                - Exciting
                - Realistic
                - No long paragraphs
                - No introductions
                - No explanations

                Score:
                %s
                """.formatted(score);
    }
}
