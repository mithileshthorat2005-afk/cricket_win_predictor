package com.example.cricket.repository;

import com.example.cricket.model.Prediction;
import org.springframework.data.jpa.repository.JpaRepository;

import java.util.List;

public interface PredictionRepository extends JpaRepository<Prediction, Long> {
    List<Prediction> findTop50ByMatchIdOrderByCreatedAtDesc(Long matchId);
}
