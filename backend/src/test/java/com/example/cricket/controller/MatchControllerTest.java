package com.example.cricket.controller;

import com.example.cricket.client.FastApiClient;
import com.example.cricket.dto.fastapi.FastApiXgbRequest;
import com.example.cricket.dto.fastapi.FastApiXgbResponse;
import com.example.cricket.exception.PredictionUnavailableException;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.http.MediaType;
import org.springframework.test.context.ActiveProfiles;
import org.springframework.test.context.bean.override.mockito.MockitoBean;
import org.springframework.test.web.servlet.MockMvc;

import java.util.List;

import static org.hamcrest.Matchers.*;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.*;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;

/**
 * REST API tests (MockMvc) with FastApiClient mocked - verifies the full
 * request -> state update -> response contract, including 404s, validation,
 * duplicate handling and prediction failures.
 */
@SpringBootTest
@AutoConfigureMockMvc
@ActiveProfiles("test")
class MatchControllerTest {

    @Autowired private MockMvc mvc;

    @MockitoBean private FastApiClient fastApiClient;

    private String createMatch() throws Exception {
        String body = mvc.perform(post("/api/matches")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"team1\":\"Team A\",\"team2\":\"Team B\"}"))
                .andExpect(status().isCreated())
                .andExpect(jsonPath("$.id").isNumber())
                .andReturn().getResponse().getContentAsString();
        return com.jayway.jsonpath.JsonPath.parse(body).read("$.id").toString();
    }

    private static String ballJson(int over, int ball, int runs, boolean wicket) {
        return """
                {"inning":1,"over":%d,"ball":%d,"striker":"Player X",
                 "bowler":"Bowler Y","runs":%d,"wicket":%s}
                """.formatted(over, ball, runs, wicket);
    }

    @Test
    void createGetAndLiveMatch() throws Exception {
        String id = createMatch();

        mvc.perform(get("/api/matches/" + id))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.team1").value("Team A"))
                .andExpect(jsonPath("$.status").value("LIVE"));

        mvc.perform(get("/api/matches/live"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$", hasSize(greaterThanOrEqualTo(1))));
    }

    @Test
    void createMatch_validationBlankTeam_rejected() throws Exception {
        mvc.perform(post("/api/matches")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"team1\":\"\",\"team2\":\"Team B\"}"))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.error").value("Validation Failed"));
    }

    @Test
    void getUnknownMatch_is404() throws Exception {
        mvc.perform(get("/api/matches/999999"))
                .andExpect(status().isNotFound())
                .andExpect(jsonPath("$.error").value("Not Found"));
    }

    @Test
    void ingestBall_updatesState_returnsDuplicateOnRetry() throws Exception {
        String id = createMatch();

        mvc.perform(post("/api/matches/" + id + "/balls")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(ballJson(0, 1, 4, false)))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.duplicate").value(false))
                .andExpect(jsonPath("$.state.runs").value(4))
                .andExpect(jsonPath("$.state.stateVersion").value(1));

        // Same event again -> duplicate, nothing double counted
        mvc.perform(post("/api/matches/" + id + "/balls")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(ballJson(0, 1, 4, false)))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.duplicate").value(true))
                .andExpect(jsonPath("$.state.runs").value(4))
                .andExpect(jsonPath("$.state.stateVersion").value(1));
    }

    @Test
    void ingestBall_validationBadBall_rejected() throws Exception {
        String id = createMatch();
        mvc.perform(post("/api/matches/" + id + "/balls")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(ballJson(0, 7, 4, false))) // ball 7 invalid
                .andExpect(status().isBadRequest());
    }

    @Test
    void predict_endpointReturnsProbability() throws Exception {
        String id = createMatch();
        when(fastApiClient.predictXgb(any(FastApiXgbRequest.class))).thenReturn(
                new FastApiXgbResponse(0.55, "Team A", "Team B", 1, "Low", List.of("Evenly poised")));

        mvc.perform(post("/api/matches/" + id + "/predict")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"model\":\"xgboost\"}"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.winProbability").value(0.55))
                .andExpect(jsonPath("$.modelType").value("xgboost"))
                .andExpect(jsonPath("$.stale").value(false));
    }

    @Test
    void predict_whenFastApiDown_returns503_neverAFabricatedProbability() throws Exception {
        String id = createMatch();
        when(fastApiClient.predictXgb(any())).thenThrow(
                new PredictionUnavailableException("FastAPI /predict failed: Connection refused"));

        mvc.perform(post("/api/matches/" + id + "/predict")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{}"))
                .andExpect(status().isServiceUnavailable())
                .andExpect(jsonPath("$.error").value("Prediction Unavailable"))
                .andExpect(jsonPath("$.message", containsString("Connection refused")));
    }

    @Test
    void predictionsHistory_isListed() throws Exception {
        String id = createMatch();
        when(fastApiClient.predictXgb(any())).thenReturn(
                new FastApiXgbResponse(0.42, "Team A", "Team B", 1, "Medium", List.of()));

        mvc.perform(post("/api/matches/" + id + "/predict")
                        .contentType(MediaType.APPLICATION_JSON).content("{}"))
                .andExpect(status().isOk());

        mvc.perform(get("/api/matches/" + id + "/predictions"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$", hasSize(1)))
                .andExpect(jsonPath("$[0].winProbability").value(0.42));
    }

    @Test
    void legacyScoreEndpoint_stillBroadcasts() throws Exception {
        // Original livecricket project contract preserved
        mvc.perform(post("/score")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"team\":\"CSK\",\"runs\":145,\"wickets\":2,\"overs\":\"15.0\"}"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.score.team").value("CSK"))
                .andExpect(jsonPath("$.commentary").isEmpty()); // AI off -> null
    }
}
