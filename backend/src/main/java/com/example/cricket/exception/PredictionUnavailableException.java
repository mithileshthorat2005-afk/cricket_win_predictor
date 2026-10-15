package com.example.cricket.exception;

/**
 * 503: the FastAPI prediction service is unreachable, timed out, or returned
 * an error. Callers must NOT fabricate a probability in this case.
 */
public class PredictionUnavailableException extends RuntimeException {
    public PredictionUnavailableException(String message) {
        super(message);
    }

    public PredictionUnavailableException(String message, Throwable cause) {
        super(message, cause);
    }
}
