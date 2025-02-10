# Monkey-patch for `typeDict` deprecation
import numpy as np
if not hasattr(np, 'typeDict'):
    np.typeDict = np.sctypeDict
######################################
"""
Multipath Scheduler Implementation with Network Testing Framework
This file combines schedulers, network condition simulation, and testing frameworks.
"""
import eventlet.wsgi
eventlet.wsgi.ALREADY_HANDLED = object()

import os
import glob
import traceback
os.environ['MPLCONFIGDIR'] = '/tmp/matplotlib-cache'
import matplotlib.pyplot as plt
import time
import random
import iperf3
import pandas as pd
import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple
import copy
from collections import deque, defaultdict
from collections.abc import MutableMapping
from enum import Enum
import json
import csv
import seaborn as sns
import psutil
from ryu.base import app_manager
from ryu.controller import ofp_event
from ryu.controller.handler import CONFIG_DISPATCHER, MAIN_DISPATCHER
from ryu.controller.handler import set_ev_cls
from ryu.ofproto import ofproto_v1_3
from ryu.lib.packet import packet, ethernet, ipv4
import itertools
from mininet.net import Mininet
from mininet.node import Controller, OVSKernelSwitch, RemoteController
from mininet.cli import CLI
from mininet.log import setLogLevel
from mininet.link import TCLink
from mininet.topo import Topo
import networkx as nx


###########################################
# Part 1: Core Data Structures and Base Classes
###########################################

@dataclass
class Packet:
    id: int
    size: int
    stream_id: str
    deadline: float
    priority: int
    creation_time: float

@dataclass
class PathState:
    id: str
    rtt: float
    bandwidth: float
    cwnd: int
    congestion_level: float
    available_buffer: int
    in_recovery: bool
    last_sent_time: float

@dataclass
class PerformanceMetrics:
    timestamp: float
    latency: float
    jitter: float
    throughput: float
    packet_loss: float
    buffer_occupancy: float
    path_utilization: float
    cwnd_size: int
    queue_length: int
    retransmissions: int

class BaseScheduler(ABC):
    def __init__(self):
        self.paths: Dict[str, PathState] = {}
        self.packets_queue: deque = deque()
        self.sent_packets: Dict[int, float] = {}
        self.stats = {
            'packets_sent': 0,
            'bytes_sent': 0,
            'retransmissions': 0
        }
        self.running = True
        self.supports_concurrent_transfer = False 
        
    @abstractmethod
    def select_path(self, packet: Packet) -> Optional[PathState]:
        pass
    
    def update_path_state(self, path_id: str, **kwargs):
        if path_id in self.paths:
            for key, value in kwargs.items():
                setattr(self.paths[path_id], key, value)
                
    def add_packet(self, packet: Packet):
        self.packets_queue.append(packet)
        
    def get_path_stats(self, path_id: str) -> dict:
        if path_id not in self.paths:
            return {}
        path = self.paths[path_id]
        return {
            'rtt': path.rtt,
            'bandwidth': path.bandwidth,
            'cwnd': path.cwnd,
            'congestion_level': path.congestion_level
        }

    def run_scheduler_loop(self):
        while self.running:
            if self.packets_queue:
                packet = self.packets_queue[0]  # Peek at the next packet
                
                selected_path = self.select_path(packet)
                if selected_path:
                    # Remove packet from queue and send it
                    self.packets_queue.popleft()
                    self.sent_packets[packet.id] = time.time()
                    self.stats['packets_sent'] += 1
                    self.stats['bytes_sent'] += packet.size
                    
                    # Update path state
                    selected_path.available_buffer -= packet.size
                    selected_path.last_sent_time = time.time()
                    
            time.sleep(0.001)  # Small delay to prevent CPU overload

class NetworkCondition(Enum):
    IDEAL = "ideal"
    HIGH_LATENCY = "high_latency"
    PACKET_LOSS = "packet_loss"
    BANDWIDTH_FLUCTUATION = "bandwidth_fluctuation"
    CONGESTION = "congestion"
    ASYMMETRIC = "asymmetric"
    INTERMITTENT = "intermittent"
    MOBILE = "mobile"
   # SATELLITE = "satellite"

class MultipathScenario(Enum):
    DISJOINT_PATHS = "disjoint_paths"
    SHARED_BOTTLENECK = "shared_bottleneck"
    PATH_DIVERSITY = "path_diversity"
    DYNAMIC_PATH = "dynamic_path"
    HETEROGENEOUS_PATHS = "heterogeneous_paths"
    OVERLAPPING_PATHS = "overlapping_paths"
    BACKUP_PATH = "backup_path"
    LOAD_BALANCING = "load_balancing"

###########################################
# Part 1: Utilities and Helper Functions
###########################################

def create_monitoring_service():
    """Create a monitoring service for scheduler comparison"""
    return {
        'ECF': SchedulerMonitor('ECF'),
        'RR': SchedulerMonitor('RR'),
        'MPS_OF_AS': SchedulerMonitor('MPS_OF_AS')
    }

def create_test_environment():
    """Create a test environment with sample paths"""
    # Create test paths
    path1 = PathState(
        id="path1",
        rtt=25.0,  # Low latency high bandwidth
        bandwidth=1000.0,  # 1000 Mbps
        cwnd=1000,
        congestion_level=0.1,
        available_buffer=64000,
        in_recovery=False,
        last_sent_time=0.0
    )
    
    path2 = PathState(
        id="path2",
        rtt=50.0,  # Medium latency medium bandwidth
        bandwidth=500.0,  # 500 Mbps
        cwnd=1000,
        congestion_level=0.2,
        available_buffer=64000,
        in_recovery=False,
        last_sent_time=0.0
    )
    path3 = PathState(
        id="path3",
        rtt=100.0,  # High latency High bandwidth
        bandwidth=800.0,  # 800 Mbps
        cwnd=1000,
        congestion_level=0.15,
        available_buffer=64000,
        in_recovery=False,
        last_sent_time=0.0
    )
    path4 = PathState(
        id="path4",
        rtt=25.0,  # low tatency low bandwidth
        bandwidth=150.0,  # 150 Mbps
        cwnd=1000,
        congestion_level=0.05,
        available_buffer=64000,
        in_recovery=False,
        last_sent_time=0.0
    )

    return {
        "path1": path1,
        "path2": path2,
        "path3": path3,
        "path4": path4,
    }

###########################################
# Part 2: Scheduler Implementations
###########################################

class ECFScheduler(BaseScheduler):
    """Earliest Completion First Scheduler Implementation"""
    
    def __init__(self):
        super().__init__()
        self.path_history = defaultdict(list)
        self.smoothing_factor = 0.125  # For EWMA calculations
        self.min_rtt_samples = 5
        self.congestion_threshold = 0.8
        
    def select_path(self, packet: Packet) -> Optional[PathState]:
        """Select path using ECF algorithm with enhanced decision making"""
        eligible_paths = self._get_eligible_paths(packet)
        if not eligible_paths:
            return None
            
        # Calculate completion time for each eligible path
        path_scores = []
        current_time = time.time()
        
        for path in eligible_paths:
            # Calculate base completion time
            transmission_time = packet.size / path.bandwidth
            propagation_time = path.rtt / 2
            queuing_delay = self._estimate_queuing_delay(path)
            
            # Calculate expected completion time
            completion_time = transmission_time + propagation_time + queuing_delay
            
            # Apply penalties for various factors
            completion_time = self._apply_penalties(
                completion_time, path, packet, current_time
            )
            
            path_scores.append((completion_time, path))
        
        # Select path with earliest completion time
        if path_scores:
            best_path = min(path_scores, key=lambda x: x[0])[1]
            self._update_path_history(best_path.id)
            return best_path
            
        return None
        
    def _get_eligible_paths(self, packet: Packet) -> List[PathState]:
        """Filter paths based on eligibility criteria"""
        eligible_paths = []
        
        for path in self.paths.values():
            # Check basic eligibility
            if (path.available_buffer >= packet.size and
                not self._is_path_congested(path)):
                
                # Check if path meets deadline requirements
                estimated_delivery = (time.time() + path.rtt + 
                                   packet.size / path.bandwidth)
                if packet.deadline == 0 or estimated_delivery <= packet.deadline:
                    eligible_paths.append(path)
                    
        return eligible_paths
        
    def _estimate_queuing_delay(self, path: PathState) -> float:
        """Estimate queuing delay based on buffer occupancy"""
        buffer_occupancy = 1 - (path.available_buffer / 64000)  # Assuming 64KB buffer
        return buffer_occupancy * path.rtt
        
    def _is_path_congested(self, path: PathState) -> bool:
        """Determine if path is congested based on multiple factors"""
        if path.congestion_level > self.congestion_threshold:
            return True
            
        # Check recent RTT trend
        rtt_samples = self.path_history[path.id][-self.min_rtt_samples:]
        if len(rtt_samples) >= self.min_rtt_samples:
            rtt_trend = np.mean(np.diff(rtt_samples))
            if rtt_trend > 0.1 * path.rtt:  # RTT increasing significantly
                return True
                
        return False
        
    def _apply_penalties(self, base_time: float, path: PathState, 
                        packet: Packet, current_time: float) -> float:
        """Apply penalties to completion time based on various factors"""
        completion_time = base_time
        
        # Penalty for congestion level
        completion_time *= (1 + path.congestion_level)
        
        # Penalty for recent failures or retransmissions
        if path.in_recovery:
            completion_time *= 1.5
            
        # Penalty for path instability
        stability_factor = self._calculate_path_stability(path.id)
        completion_time *= (1 + (1 - stability_factor))
        
        # Priority-based adjustment
        if packet.priority > 0:
            completion_time /= packet.priority
            
        return completion_time
        
    def _calculate_path_stability(self, path_id: str) -> float:
        """Calculate path stability based on historical performance"""
        history = self.path_history[path_id]
        if len(history) < 2:
            return 1.0
            
        # Calculate RTT variance
        rtt_variance = np.var(history) / np.mean(history)
        
        # Convert to stability score (0 to 1)
        stability = 1 / (1 + rtt_variance)
        return stability
        
    def _update_path_history(self, path_id: str):
        """Update path history with latest RTT measurement"""
        current_rtt = self.paths[path_id].rtt
        history = self.path_history[path_id]
        
        # Apply EWMA for smoothing
        if history:
            smoothed_rtt = (self.smoothing_factor * current_rtt + 
                          (1 - self.smoothing_factor) * history[-1])
            history.append(smoothed_rtt)
        else:
            history.append(current_rtt)
            
        # Keep history bounded
        if len(history) > 100:
            history.pop(0)

class RRScheduler(BaseScheduler):
    """Round Robin Scheduler Implementation with enhancements"""
    
    def __init__(self):
        super().__init__()
        self.current_path_index = 0
        self.path_weights = {}
        self.path_counters = defaultdict(int)
        self.last_adjustment_time = time.time()
        self.adjustment_interval = 1.0  # 1 second
        
    def select_path(self, packet: Packet) -> Optional[PathState]:
        """Select path using weighted round-robin with dynamic adjustment"""
        eligible_paths = self._get_eligible_paths(packet)
        if not eligible_paths:
            return None
            
        # Update weights periodically
        current_time = time.time()
        if current_time - self.last_adjustment_time > self.adjustment_interval:
            self._adjust_weights()
            self.last_adjustment_time = current_time
            
        # Select path using weighted round-robin
        selected_path = self._weighted_round_robin_select(eligible_paths)
        if selected_path:
            self.path_counters[selected_path.id] += 1
            
        return selected_path
        
    def _get_eligible_paths(self, packet: Packet) -> List[PathState]:
        """Filter paths based on eligibility criteria"""
        return [path for path in self.paths.values()
                if path.available_buffer >= packet.size
                and not path.in_recovery]
                
    def _adjust_weights(self):
        """Dynamically adjust path weights based on performance"""
        total_bandwidth = sum(path.bandwidth for path in self.paths.values())
        total_packets = sum(self.path_counters.values()) or 1
        
        for path_id, path in self.paths.items():
            # Calculate base weight from bandwidth proportion
            bandwidth_weight = path.bandwidth / total_bandwidth
            
            # Adjust weight based on RTT
            rtt_factor = min(1.0, 50.0 / path.rtt)  # Normalize RTT impact
            
            # Adjust weight based on congestion
            congestion_factor = 1.0 - path.congestion_level
            
            # Adjust weight based on historical usage
            usage_rate = self.path_counters[path_id] / total_packets
            balance_factor = 1.0 - usage_rate
            
            # Combine factors
            self.path_weights[path_id] = (bandwidth_weight * 
                                        rtt_factor * 
                                        congestion_factor * 
                                        balance_factor)
            
        # Normalize weights
        weight_sum = sum(self.path_weights.values())
        if weight_sum > 0:
            for path_id in self.path_weights:
                self.path_weights[path_id] /= weight_sum
                
    def _weighted_round_robin_select(self, 
                                   eligible_paths: List[PathState]) -> Optional[PathState]:
        """Select path using weighted round-robin algorithm"""
        if not eligible_paths:
            return None
            
        # Filter weights for eligible paths
        eligible_weights = {path.id: self.path_weights.get(path.id, 1.0)
                          for path in eligible_paths}
        
        # Normalize weights for eligible paths
        weight_sum = sum(eligible_weights.values())
        if weight_sum > 0:
            normalized_weights = {
                path_id: weight / weight_sum
                for path_id, weight in eligible_weights.items()
            }
        else:
            # Equal weights if all weights are zero
            weight = 1.0 / len(eligible_paths)
            normalized_weights = {path.id: weight for path in eligible_paths}
            
        # Select path based on weights
        selection = random.random()
        cumulative = 0.0
        
        for path in eligible_paths:
            cumulative += normalized_weights[path.id]
            if selection <= cumulative:
                return path
                
        return eligible_paths[-1]  # Fallback to last path if no selection made

class MPS_OF_ASScheduler(BaseScheduler):
    def __init__(self):
        super().__init__()
        self.parameters = {
            'bandwidth_weight': 0.35,
            'latency_weight': 0.25,
            'congestion_weight': 0.20,
            'buffer_weight': 0.10,
            'historical_weight': 0.10
        }
        self.path_history = defaultdict(list)
        self.max_concurrent_paths = 3
        self.path_scores_cache = {}
        self.score_cache_timeout = 0.5  # seconds
        self.last_score_update = 0
        self.supports_concurrent_transfer = True
        self.min_chunk_size = 1800  # Minimum chunk size (MTU-like)

    def select_path(self, packet: Packet) -> Dict[str, int]:
        
        current_time = time.time()
        
        # Update path scores if cache expired
        if current_time - self.last_score_update > self.score_cache_timeout:
            self._update_path_scores()
            self.last_score_update = current_time

        # Get best paths based on cached scores
        best_paths = self._get_best_paths()
        
        # If no suitable paths found, return empty distribution
        if not best_paths:
            return {}

        # Distribute packet across selected paths
        return self.distribute_packets(packet, best_paths)

    def _update_path_scores(self):
        """Update scores for all paths"""
        self.path_scores_cache.clear()
        
        for path_id, path in self.paths.items():
            if not self._is_path_eligible(path):
                continue
                
            score = self._calculate_path_score(path)
            self.path_scores_cache[path_id] = score

    def _is_path_eligible(self, path: PathState) -> bool:
        """Check if path is eligible for transmission"""
        return (path.available_buffer >= self.min_chunk_size and 
                path.congestion_level < 0.8 and 
                not path.in_recovery)

    def _calculate_path_score(self, path: PathState) -> float:
        """Calculate comprehensive path score"""
        # Normalize metrics
        max_bandwidth = max(p.bandwidth for p in self.paths.values())
        min_rtt = min(p.rtt for p in self.paths.values())
        max_buffer = max(p.available_buffer for p in self.paths.values())

        bandwidth_score = path.bandwidth / max_bandwidth if max_bandwidth > 0 else 0
        latency_score = min_rtt / path.rtt if path.rtt > 0 else 0
        congestion_score = 1 - path.congestion_level
        buffer_score = path.available_buffer / max_buffer if max_buffer > 0 else 0
        
        # Get historical performance
        historical_score = self._get_historical_score(path.id)

        # Calculate weighted score
        score = (
            self.parameters['bandwidth_weight'] * bandwidth_score +
            self.parameters['latency_weight'] * latency_score +
            self.parameters['congestion_weight'] * congestion_score +
            self.parameters['buffer_weight'] * buffer_score +
            self.parameters['historical_weight'] * historical_score
        )

        return score

    def _get_historical_score(self, path_id: str) -> float:
        """Calculate historical performance score"""
        history = self.path_history[path_id]
        if not history:
            return 0.5  # Default score for new paths
            
        recent_history = history[-10:]  # Consider last 10 transmissions
        success_rate = sum(1 for result in recent_history if result) / len(recent_history)
        return success_rate

    def _get_best_paths(self) -> List[Tuple[str, float]]:
        """Get the best paths based on scores"""
        # Sort paths by score
        sorted_paths = sorted(
            self.path_scores_cache.items(),
            key=lambda x: x[1],
            reverse=True
        )
        
        # Return top paths (up to max_concurrent_paths)
        return sorted_paths[:self.max_concurrent_paths]

    def distribute_packets(self, packet: Packet,  selected_paths: List[Tuple[str, float]]) -> Dict[str, int]:
        """Distribute packet across selected paths"""
        if not selected_paths:
            return {}

        total_score = sum(score for _, score in selected_paths)
        distribution = {}
        remaining_size = packet.size

        # Distribute proportionally to path scores
        for path_id, score in selected_paths:
            if remaining_size < self.min_chunk_size:
                break

            path = self.paths[path_id]
            proportion = score / total_score
            
            # Calculate chunk size based on proportion and constraints
            chunk_size = min(
                int(packet.size * proportion),
                path.available_buffer,
                remaining_size
            )
            
            # Ensure chunk size meets minimum requirement
            if chunk_size >= self.min_chunk_size:
                distribution[path_id] = chunk_size
                remaining_size -= chunk_size

        # If there's remaining size, add it to the best path
        if remaining_size > 0 and distribution:
            best_path_id = selected_paths[0][0]
            distribution[best_path_id] += remaining_size

        return distribution

    def update_path_history(self, path_id: str, success: bool):
        """Update path transmission history"""
        history = self.path_history[path_id]
        history.append(success)
        
        # Keep history bounded
        if len(history) > 100:
            history.pop(0)

    def transmit_packet(self, packet: Packet):
        """Handle packet transmission across multiple paths"""
        path_distribution = self.select_path(packet)
        
        if not path_distribution:
            return False

        transmission_results = []
        
        # Create threads for concurrent transmission
        threads = []
        results = {}

        def transmit_chunk(path_id: str, chunk_size: int):
            path = self.paths[path_id]
            # Simulate transmission
            success = random.random() > path.congestion_level
            results[path_id] = success
            
            if success:
                # Update path state
                path.available_buffer -= chunk_size
                path.last_sent_time = time.time()

        # Start concurrent transmissions
        for path_id, chunk_size in path_distribution.items():
            thread = threading.Thread(
                target=transmit_chunk,
                args=(path_id, chunk_size)
            )
            thread.start()
            threads.append(thread)

        # Wait for all transmissions to complete
        for thread in threads:
            thread.join()

        # Update path history with results
        for path_id, success in results.items():
            self.update_path_history(path_id, success)

        # Return True if any path succeeded
        return any(results.values())
###########################################
# Part 3: Monitoring and Analysis Systems
###########################################

class SchedulerMonitor:
    """Monitor and collect metrics for scheduler performance"""
    
    def __init__(self, scheduler_name: str):
        self.scheduler_name = scheduler_name
        self.metrics_history = []
        self.start_time = None
        self.is_monitoring = False
        self.sampling_interval = 0.1  # 100ms sampling
        self.monitor_thread = None
        self.analysis_results = {}

    def start_monitoring(self):
        self.start_time = time.time()
        self.is_monitoring = True
        self.metrics_history.clear()
        self.monitor_thread = threading.Thread(target=self._monitoring_loop)
        self.monitor_thread.daemon = True
        self.monitor_thread.start()

    def stop_monitoring(self):
        self.is_monitoring = False
        if self.monitor_thread:
            self.monitor_thread.join()
        self._analyze_results()

    def _monitoring_loop(self):
        while self.is_monitoring:
            metrics = self._collect_metrics()
            self.metrics_history.append(metrics)
            time.sleep(self.sampling_interval)

    def _collect_metrics(self) -> PerformanceMetrics:
        current_time = time.time()
        latency = random.uniform(10, 100)  # Simulate latency in ms
        jitter = random.uniform(1, 10)  # Simulate jitter in ms
        throughput = random.uniform(50, 100)  # Simulate throughput in Mbps
        packet_loss = random.uniform(0.01, 0.05)  # Simulate packet loss rate
        buffer_occupancy = random.uniform(0, 1) * 64000  # Simulate buffer usage
        path_utilization = random.uniform(0.5, 1.0)  # Simulate path utilization
        cwnd_size = random.randint(500, 1000)  # Simulate congestion window size
        queue_length = random.randint(0, 50)  # Simulate queue length
        retransmissions = random.randint(0, 10)  # Simulate retransmissions

        return PerformanceMetrics(
            timestamp=current_time - self.start_time,
            latency=latency,
            jitter=jitter,
            throughput=throughput,
            packet_loss=packet_loss,
            buffer_occupancy=buffer_occupancy,
            path_utilization=path_utilization,
            cwnd_size=cwnd_size,
            queue_length=queue_length,
            retransmissions=retransmissions,
        )

    def _analyze_results(self):
        if not self.metrics_history:
            return

        metrics_array = np.array([
            [m.latency, m.throughput, m.packet_loss, m.path_utilization]
            for m in self.metrics_history
        ])

        self.analysis_results = {
            'latency': {
                'mean': np.mean(metrics_array[:, 0]),
                'std': np.std(metrics_array[:, 0]),
                'percentile_95': np.percentile(metrics_array[:, 0], 95)
            },
            'throughput': {
                'mean': np.mean(metrics_array[:, 1]),
                'std': np.std(metrics_array[:, 1]),
                'stability': 1.0 / (1.0 + np.std(metrics_array[:, 1]) / np.mean(metrics_array[:, 1]))
            },
            'packet_loss': {
                'mean': np.mean(metrics_array[:, 2]),
                'max': np.max(metrics_array[:, 2])
            },
            'path_utilization': {
                'mean': np.mean(metrics_array[:, 3]),
                'efficiency': np.mean(metrics_array[:, 3]) * (
                    1.0 - np.std(metrics_array[:, 3]) / np.max(metrics_array[:, 3])
                )
            },
            'overall_score': self._calculate_overall_score(metrics_array)
        }

    def _calculate_stability(self, metric_series: np.ndarray) -> float:
        """Calculate stability score based on metric variance"""
        if len(metric_series) < 2:
            return 1.0
        return 1.0 / (1.0 + np.std(metric_series) / np.mean(metric_series))
        
    def _calculate_efficiency(self, utilization_series: np.ndarray) -> float:
        """Calculate path utilization efficiency"""
        return np.mean(utilization_series) * (
            1.0 - np.std(utilization_series) / np.max(utilization_series)
        )
        
    def _calculate_overall_score(self, metrics_array: np.ndarray) -> float:
        """Calculate overall performance score"""
        weights = {
            'latency': 0.3,
            'throughput': 0.3,
            'packet_loss': 0.2,
            'utilization': 0.2
        }
        
        # Normalize metrics
        normalized_metrics = self._normalize_metrics(metrics_array)
        
        # Calculate weighted score
        score = (
            weights['latency'] * (1 - normalized_metrics[:, 0].mean()) +  # Lower latency is better
            weights['throughput'] * normalized_metrics[:, 1].mean() +     # Higher throughput is better
            weights['packet_loss'] * (1 - normalized_metrics[:, 2].mean()) +  # Lower loss is better
            weights['utilization'] * normalized_metrics[:, 3].mean()      # Higher utilization is better
        )
        
        return score
        
    def _normalize_metrics(self, metrics_array: np.ndarray) -> np.ndarray:
        """Normalize metrics to [0, 1] range"""
        normalized = np.zeros_like(metrics_array)
        
        for i in range(metrics_array.shape[1]):
            min_val = np.min(metrics_array[:, i])
            max_val = np.max(metrics_array[:, i])
            
            if max_val > min_val:
                normalized[:, i] = (metrics_array[:, i] - min_val) / (max_val - min_val)
            else:
                normalized[:, i] = 0.5  # Default value if no variation
                
        return normalized

class PerformanceAnalyzer:
    def __init__(self, monitors: Dict[str, SchedulerMonitor]):
        self.monitors = monitors
        self.comparison_results = {}
        
    def analyze_all(self):
        """Perform comprehensive analysis of all schedulers"""
        # First ensure all monitors have analyzed their results
        for monitor in self.monitors.values():
            if not hasattr(monitor, 'analysis_results'):
                monitor.analysis_results = {}
            if 'overall_score' not in monitor.analysis_results:
                # Calculate basic score if none exists
                monitor.analysis_results['overall_score'] = self._calculate_basic_score(monitor)
        
        self.comparison_results = {
            'overall_ranking': self._rank_schedulers(),
            'detailed_comparison': self._compare_metrics(),
            'stability_analysis': self._analyze_stability(),
            'efficiency_analysis': self._analyze_efficiency(),
            'recommendations': self._generate_recommendations()
        }
        
    def _calculate_basic_score(self, monitor: SchedulerMonitor) -> float:
        """Calculate a basic score based on available metrics"""
        if not monitor.metrics_history:
            return 0.0
        
        # Calculate average metrics
        latency_scores = []
        throughput_scores = []
        for metric in monitor.metrics_history:
            if hasattr(metric, 'latency'):
                latency_scores.append(metric.latency)
            if hasattr(metric, 'throughput'):
                throughput_scores.append(metric.throughput)
            
        # Normalize and combine scores
        score = 0.0
    
        # Handle latency scores
        if latency_scores:
            max_latency = max(latency_scores)
            if max_latency > 0:
                latency_score = 1 - (sum(latency_scores) / len(latency_scores) / max_latency)
                score += latency_score * 0.5
        
        # Handle throughput scores
        if throughput_scores:
            max_throughput = max(throughput_scores)
            if max_throughput > 0:
                throughput_score = sum(throughput_scores) / len(throughput_scores) / max_throughput
                score += throughput_score * 0.5
        
        return max(0.0, min(1.0, score))  # Ensure score is between 0 and 1
        
    def _rank_schedulers(self) -> Dict[str, float]:
        """Rank schedulers based on overall performance"""
        scores = {}
        for name, monitor in self.monitors.items():
            scores[name] = monitor.analysis_results.get('overall_score', 0.0)
        
        # Normalize scores, handling the case where all scores are 0
        max_score = max(scores.values())
        if max_score == 0:
            # If all scores are 0, return equal rankings
            return {name: 1.0 for name in scores.keys()}
    
        return {name: score/max_score for name, score in scores.items()}
        
    def _compare_metrics(self) -> Dict:
        """Compare detailed metrics across schedulers"""
        metrics_comparison = {}
        
        for metric in ['latency', 'throughput', 'packet_loss', 'path_utilization']:
            metric_data = {}
            for name, monitor in self.monitors.items():
                metric_data[name] = monitor.analysis_results[metric]
            metrics_comparison[metric] = metric_data
            
        return metrics_comparison
        
    def _analyze_stability(self) -> Dict:
        """Analyze stability characteristics of each scheduler"""
        stability_analysis = {}
        
        for name, monitor in self.monitors.items():
            metrics = monitor.metrics_history
            stability_analysis[name] = {
                'throughput_stability': self._calculate_stability_score(
                    [m.throughput for m in metrics]
                ),
                'latency_stability': self._calculate_stability_score(
                    [m.latency for m in metrics]
                ),
                'overall_stability': monitor.analysis_results['throughput']['stability']
            }
            
        return stability_analysis
        
    def _analyze_efficiency(self) -> Dict:
        """Analyze resource utilization efficiency"""
        efficiency_analysis = {}
        
        for name, monitor in self.monitors.items():
            metrics = monitor.metrics_history
            efficiency_analysis[name] = {
                'path_efficiency': monitor.analysis_results['path_utilization']['efficiency'],
                'resource_utilization': self._calculate_resource_efficiency(metrics),
                'adaptation_speed': self._calculate_adaptation_speed(metrics)
            }
            
        return efficiency_analysis
        
    def _generate_recommendations(self) -> Dict:
        """Generate recommendations based on analysis"""
        recommendations = {}
        
        # Analyze each scheduler's strengths and weaknesses
        for name, monitor in self.monitors.items():
            analysis = monitor.analysis_results
            strengths = []
            weaknesses = []
            
            # Analyze latency
            if analysis['latency']['mean'] < 50:  # Example threshold
                strengths.append("Low latency")
            else:
                weaknesses.append("High latency")
                
            # Analyze throughput
            if analysis['throughput']['stability'] > 0.8:
                strengths.append("Stable throughput")
            else:
                weaknesses.append("Unstable throughput")
                
            # Generate recommendations
            recommendations[name] = {
                'strengths': strengths,
                'weaknesses': weaknesses,
                'suggested_improvements': self._suggest_improvements(weaknesses),
                'best_use_cases': self._determine_use_cases(strengths)
            }
            
        return recommendations
        
    def _calculate_stability_score(self, metric_series: List[float]) -> float:
        """Calculate stability score for a metric series"""
        if not metric_series:
            return 0.0
            
        values = np.array(metric_series)
        return 1.0 / (1.0 + np.std(values) / np.mean(values))
        
    def _calculate_resource_efficiency(self, metrics: List[PerformanceMetrics]) -> float:
        """Calculate resource utilization efficiency"""
        if not metrics:
            return 0.0
            
        throughput_values = np.array([m.throughput for m in metrics])
        buffer_usage = np.array([m.buffer_occupancy for m in metrics])
        
        # Combine throughput efficiency with buffer efficiency
        throughput_efficiency = np.mean(throughput_values) / np.max(throughput_values)
        buffer_efficiency = 1.0 - np.mean(buffer_usage)  # Lower buffer usage is better
        
        return 0.7 * throughput_efficiency + 0.3 * buffer_efficiency
        
    def _calculate_adaptation_speed(self, metrics: List[PerformanceMetrics]) -> float:
        """Calculate how quickly the scheduler adapts to changes"""
        if len(metrics) < 2:
            return 0.0
            
        # Calculate rate of change in throughput
        throughput_changes = np.diff([m.throughput for m in metrics])
        return np.mean(np.abs(throughput_changes))
        
    def _suggest_improvements(self, weaknesses: List[str]) -> List[str]:
        """Suggest improvements based on identified weaknesses"""
        suggestions = []
        for weakness in weaknesses:
            if "High latency" in weakness:
                suggestions.append("Consider implementing predictive path selection")
            elif "Unstable throughput" in weakness:
                suggestions.append("Implement better congestion control mechanisms")
            # Add more suggestions based on other weaknesses
        return suggestions
        
    def _determine_use_cases(self, strengths: List[str]) -> List[str]:
        """Determine best use cases based on strengths"""
        use_cases = []
        if "Low latency" in strengths:
            use_cases.append("Real-time applications")
        if "Stable throughput" in strengths:
            use_cases.append("Streaming media")
        # Add more use cases based on other strengths
        return use_cases
###########################################
# Part 4: Testing Framework and Visualization
###########################################

#############TOPOLOGY BASE#################
class FatTreeTopo(Topo):
    """8-ary Fat Tree topology"""
    
    def __init__(self):
        super(FatTreeTopo, self).__init__()
        
        # Fat-tree parameters
        self.k = 4  # K-ary fat tree
        self.pod = self.k
        self.core_switches = (self.k//2)**2
        self.aggr_switches_per_pod = self.k//2
        self.edge_switches_per_pod = self.k//2
        self.hosts_per_edge = self.k//2
        
        # Create switches and hosts
        self._create_core_switches()
        self._create_aggregation_switches()
        self._create_edge_switches()
        self._create_hosts()
        self._create_links()
        
    def _create_core_switches(self):
        for i in range(self.core_switches):
            self.addSwitch(f'c{i}')
            
    def _create_aggregation_switches(self):
        for pod in range(self.pod):
            for switch in range(self.aggr_switches_per_pod):
                self.addSwitch(f'a{pod}{switch}')
                
    def _create_edge_switches(self):
        for pod in range(self.pod):
            for switch in range(self.edge_switches_per_pod):
                self.addSwitch(f'e{pod}{switch}')
                
    def _create_hosts(self):
        for pod in range(self.pod):
            for edge in range(self.edge_switches_per_pod):
                for host in range(self.hosts_per_edge):
                    self.addHost(f'h{pod}{edge}{host}')
                    
    def _create_links(self):
        # Connect core to aggregation
        core_index = 0
        for pod in range(self.pod):
            for aggr in range(self.aggr_switches_per_pod):
                for j in range(self.k//2):
                    self.addLink(f'c{core_index}', f'a{pod}{aggr}')
                    core_index = (core_index + 1) % self.core_switches
                    
        # Connect aggregation to edge
        for pod in range(self.pod):
            for aggr in range(self.aggr_switches_per_pod):
                for edge in range(self.edge_switches_per_pod):
                    self.addLink(f'a{pod}{aggr}', f'e{pod}{edge}')
                    
        # Connect edge to hosts
        for pod in range(self.pod):
            for edge in range(self.edge_switches_per_pod):
                for host in range(self.hosts_per_edge):
                    self.addLink(f'e{pod}{edge}', f'h{pod}{edge}{host}')
    
    def convert_to_nx_graph(self):
        """Convert the FatTree topology to a NetworkX graph"""
        G = nx.Graph()
    
        # Add all switches and hosts as nodes
        for node in self.nodes(sort=True):  # Use sort=True to ensure consistent ordering
            G.add_node(node)
    
        # Add all links as edges
        for src, dst in self.links(sort=True, withKeys=False):  # Add links without keys
            G.add_edge(src, dst)
    
        return G
class JellyfishTopo(Topo):
    """Jellyfish topology"""
    
    def __init__(self, n_switches=64, n_ports=8, n_hosts=64):
        super(JellyfishTopo, self).__init__()
        
        self.n_switches = n_switches
        self.n_ports = n_ports
        self.n_hosts = n_hosts
        
        # Create switches and hosts
        self._create_switches()
        self._create_hosts()
        self._create_random_topology()
        
    def _create_switches(self):
        for i in range(self.n_switches):
            self.addSwitch(f's{i}')
            
    def _create_hosts(self):
        for i in range(self.n_hosts):
            self.addHost(f'h{i}')
            # Connect each host to a switch
            self.addLink(f'h{i}', f's{i % self.n_switches}')
            
    def _create_random_topology(self):
        # Create random switch-to-switch connections
        G = nx.random_regular_graph(self.n_ports - 1, self.n_switches)
        
        for (u, v) in G.edges():
            self.addLink(f's{u}', f's{v}')
    
    def convert_to_nx_graph(self):
        """Convert the Jellyfish topology to a NetworkX graph"""
        G = nx.Graph()
    
        # Add all switches and hosts as nodes
        for node in self.nodes(sort=True):  # Use sort=True to ensure consistent ordering
            G.add_node(node)
    
        # Add all links as edges
        for src, dst in self.links(sort=True, withKeys=False):  # Add links without keys
            G.add_edge(src, dst)
    
        return G
#####################CONTROLLER################
class MPQUICController(app_manager.RyuApp):
    """Ryu controller for MPQUIC traffic management"""
    
    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]
    
    def __init__(self, *args, **kwargs):
        super(MPQUICController, self).__init__(*args, **kwargs)
        self.mac_to_port = {}
        self.paths = {}  # Store computed paths
        
    @set_ev_cls(ofp_event.EventOFPSwitchFeatures, CONFIG_DISPATCHER)
    def switch_features_handler(self, ev):
        datapath = ev.msg.datapath
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        
        # Install default flow
        match = parser.OFPMatch()
        actions = [parser.OFPActionOutput(ofproto.OFPP_CONTROLLER,
                                        ofproto.OFPCML_NO_BUFFER)]
        self.add_flow(datapath, 0, match, actions)
        
    def add_flow(self, datapath, priority, match, actions, buffer_id=None):
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        
        inst = [parser.OFPInstructionActions(ofproto.OFPIT_APPLY_ACTIONS,
                                           actions)]
        if buffer_id:
            mod = parser.OFPFlowMod(datapath=datapath, buffer_id=buffer_id,
                                  priority=priority, match=match,
                                  instructions=inst)
        else:
            mod = parser.OFPFlowMod(datapath=datapath, priority=priority,
                                  match=match, instructions=inst)
        datapath.send_msg(mod)
        
    def _compute_paths(self, src, dst, k=4):
        """Compute k-shortest paths between src and dst"""
        try:
            paths = list(itertools.islice(
                nx.shortest_simple_paths(self.network_graph, src, dst), k))
            return paths
        except:
            return []
            
class NetworkTestFramework:
    """Enhanced network testing framework with Mininet and Ryu"""
    
    def __init__(self, schedulers: Dict, monitor_service: Dict):
        self.schedulers = schedulers
        self.monitor_service = monitor_service
        self.net = None
        self.controller = None
        self.topology = None
        self.test_scenarios = self._init_test_scenarios()
        self.results_repository = defaultdict(dict)
        self.visualization_engine = VisualizationEngine()
        self.n_paths = 4  # Number of paths for MPQUIC
        self.paths = create_test_environment()  # Initialize paths here

        # Assign paths to schedulers
        for scheduler in self.schedulers.values():
            scheduler.paths = self.paths

    def _init_test_scenarios(self) -> Dict:
        """Initialize test scenarios configuration from a JSON file"""
        try:
            with open('test_scenarios.json', 'r') as f:
                scenarios = json.load(f)
        
            # Convert string keys to NetworkCondition Enum
            return {getattr(NetworkCondition, key): value for key, value in scenarios.items()}
    
        except Exception as e:
            print(f"Error loading test scenarios: {e}")
            return {}    
    

    def setup_network(self, topo_type='fat-tree'):
        """Set up the network topology"""
        if topo_type == 'fat-tree':
            self.topology = FatTreeTopo()
        elif topo_type == 'jellyfish':
            self.topology = JellyfishTopo()
        else:
            print(f"Unsupported topology type: {topo_type}")
            
        self.controller = RemoteController('c0', ip='127.0.0.1', port=6653)
        self.net = Mininet(topo=self.topology, 
                          controller=self.controller,
                          switch=OVSKernelSwitch,
                          link=TCLink
        )
                      
    def run_comprehensive_tests(self):
        """Run tests with both topologies and traffic patterns"""
        for topo_type in ['fat-tree', 'jellyfish']:
            print(f"\nTesting with {topo_type} topology...")
            self.setup_network(topo_type)  # Ensure this line executes
            self.net.start()

            # Initialize QUIC transfer scenario
            quic_scenario = MPQUICTransferScenario(self.net, self.schedulers, self)

            # Run QUIC transfer experiments
            quic_scenario.run_transfer_experiments(topo_type)

            self.net.stop()

    
    def _run_condition_tests(self, condition: NetworkCondition) -> Dict:
        """Run tests for specific network condition"""
        condition_results = {}
        config = self.test_scenarios[condition]

        for name, scheduler in self.schedulers.items():
            print(f"Testing {name} scheduler...")
        
            # Start monitoring
            self.monitor_service[name].start_monitoring()
        
            # Configure network conditions
            self._configure_network(config)
        
            # Run test workload for both elephant and mice flows
            for flow_type in ['elephant', 'mice']:
                print(f"Testing {flow_type} flow...")
                flow_params = self.setup_flow_parameters(flow_type)
                performance = self.measure_performance(
                    name, flow_type, src_host, dst_host, flow_params
                )
                condition_results[name] = performance
        
            # Stop monitoring
            self.monitor_service[name].stop_monitoring()
        
            # Store results
            condition_results[name] = {
                'metrics': performance,
                'monitor_data': self.monitor_service[name].metrics_history
            }
        
        # Save results for this condition
        self.save_results(condition_results, condition)


    def _configure_network(self, config: Dict):
        """Configure network conditions based on test configuration"""
        try:
            for path in self.paths.values():
                # Set latency
                if isinstance(config['latency'], list):
                    path.rtt = random.uniform(config['latency'][0], config['latency'][1])
                elif isinstance(config['latency'], dict):
                    if config['latency']['pattern'] == 'random_walk':
                        path.rtt = random.uniform(config['latency']['min'], 
                                               config['latency']['max'])
                        
                # Set bandwidth
                if isinstance(config['bandwidth'], list):
                    path.bandwidth = random.uniform(config['bandwidth'][0], 
                                                 config['bandwidth'][1])
                elif isinstance(config['bandwidth'], dict):
                    if 'pattern' in config['bandwidth']:
                        path.bandwidth = random.uniform(config['bandwidth']['min'], 
                                                     config['bandwidth']['max'])
                    else:
                        path.bandwidth = random.uniform(config['bandwidth']['min'], 
                                                     config['bandwidth']['max'])
                        
                # Set packet loss
                if isinstance(config['loss'], list):
                    path.congestion_level = config['loss'][0] / 100.0
                elif isinstance(config['loss'], dict):
                    if config['loss']['pattern'] == 'burst':
                        path.congestion_level = random.uniform(config['loss']['min'], 
                                                            config['loss']['max']) / 100.0
                        
                # Configure cross traffic if enabled
                if 'cross_traffic' in config and config['cross_traffic']['enabled']:
                    path.available_buffer *= (1 - config['cross_traffic']['intensity'])
                    
        except Exception as e:
            print(f"Error configuring network: {str(e)}")

    
    def _run_test_workload(self, scheduler, config: Dict) -> Dict:
        """Run test workload and collect metrics"""
        try:
            # Initialize metrics
            metrics = {
                'latency': {'values': [], 'mean': 0, 'std': 0},
                'throughput': {'values': [], 'mean': 0, 'std': 0},
                'packet_loss': {'values': [], 'mean': 0, 'std': 0},
                'path_utilization': {'values': [], 'mean': 0, 'std': 0}
            }
        
            # Ensure scheduler has paths initialized
            if not scheduler.paths:
                scheduler.paths = create_test_environment()
        
            # Generate test traffic
            duration = config.get('duration', 60)  # Default 60 seconds
            start_time = time.time()
            packet_id = 0
        
            while time.time() - start_time < duration:
                # Generate test packet
                packet = Packet(
                    id=packet_id,
                    size=1500,  # Standard MTU size
                    stream_id="test_stream",
                    deadline=time.time() + 0.1,  # 100ms deadline
                    priority=1,
                    creation_time=time.time()
                )
            
                # Schedule packet
                selected_path = scheduler.select_path(packet)
                if selected_path:
                    # Record metrics
                    latency = selected_path.rtt
                    throughput = selected_path.bandwidth
                    loss_rate = selected_path.congestion_level
                    utilization = 1 - (selected_path.available_buffer / 64000)
                
                    metrics['latency']['values'].append(latency)
                    metrics['throughput']['values'].append(throughput)
                    metrics['packet_loss']['values'].append(loss_rate)
                    metrics['path_utilization']['values'].append(utilization)
            
                packet_id += 1
                time.sleep(0.001)  # Small delay between packets
        
            # Calculate statistics
            for metric in metrics.keys():
                values = metrics[metric]['values']
                if values:
                    metrics[metric]['mean'] = np.mean(values)
                    metrics[metric]['std'] = np.std(values)
        
            return metrics
        
        except Exception as e:
            print(f"Error running test workload: {str(e)}")
            return {
                'latency': {'values': [], 'mean': 0, 'std': 0},
                'throughput': {'values': [], 'mean': 0, 'std': 0},
                'packet_loss': {'values': [], 'mean': 0, 'std': 0},
                'path_utilization': {'values': [], 'mean': 0, 'std': 0}
        }

    def save_results(self, condition_results: Dict, condition: str, topology_type: str):
    

        overall_performance = {}  # ✅ Store total values per scheduler

        for flow_type in ['elephant', 'mice']:
            all_results = []

            for scheduler_name, performance in condition_results.get(flow_type, {}).items():
                scheduler_data = performance
                scheduler_data['scheduler'] = scheduler_name
                scheduler_data['network_condition'] = condition
                scheduler_data['topology'] = topology_type
                all_results.append(scheduler_data)

                #  Aggregate values for overall performance ranking
                if scheduler_name not in overall_performance:
                    overall_performance[scheduler_name] = {
                        'completion_time': [],
                        'throughput': [],
                        'packet_loss': [],
                        'latency': [],
                        'fairness_index': [],
                        'path_efficiency': []  # ✅ New metric added
                    }

                overall_performance[scheduler_name]['completion_time'].append(performance['completion_time'])
                overall_performance[scheduler_name]['throughput'].append(performance['throughput'])
                overall_performance[scheduler_name]['packet_loss'].append(performance['packet_loss'])
                overall_performance[scheduler_name]['latency'].append(performance['latency'])
                overall_performance[scheduler_name]['fairness_index'].append(performance['fairness_index'])
                overall_performance[scheduler_name]['path_efficiency'].append(performance['path_efficiency'])

            if not all_results:
                print(f"⚠ No results to save for {condition} - {flow_type} - {topology_type}")
                continue  # Skip if no data available

            # ✅ Save individual results
            results_df = pd.DataFrame(all_results)
            csv_filename = f"results_{topology_type}_{condition}_{flow_type}.csv"
            excel_filename = f"results_{topology_type}_{condition}_{flow_type}.xlsx"
            results_df.to_csv(csv_filename, index=False)
            results_df.to_excel(excel_filename, index=False)
            print(f"✅ Saved results for {topology_type} - {condition} - {flow_type} in {csv_filename} and {excel_filename}")

        # ✅ Compute Final Ranking for Schedulers in This Topology
        ranking_results = []
        for scheduler, metrics in overall_performance.items():
            avg_completion_time = np.mean(metrics['completion_time'])
            avg_throughput = np.mean(metrics['throughput'])
            avg_packet_loss = np.mean(metrics['packet_loss'])
            avg_latency = np.mean(metrics['latency'])
            avg_fairness = np.mean(metrics['fairness_index'])
            avg_path_efficiency = np.mean(metrics['path_efficiency'])  # ✅ Include Path Efficiency

            ranking_results.append({
                'scheduler': scheduler,
                'topology': topology_type,
                'completion_time': avg_completion_time,
                'throughput': avg_throughput,
                'packet_loss': avg_packet_loss,
                'latency': avg_latency,
                'fairness_index': avg_fairness,
                'path_efficiency': avg_path_efficiency  # ✅ New metric included in ranking
            })

        # ✅ Sort schedulers based on best performance
        ranking_df = pd.DataFrame(ranking_results)
        ranking_df.sort_values(by=['completion_time', 'throughput', 'latency', 'fairness_index', 'path_efficiency'], 
                       ascending=[True, False, True, False, False], inplace=True)


        # ✅ Save Overall Performance Results
        ranking_csv = f"overall_ranking_{topology_type}.csv"
        ranking_excel = f"overall_ranking_{topology_type}.xlsx"
        ranking_df.to_csv(ranking_csv, index=False)
        ranking_df.to_excel(ranking_excel, index=False)

        print(f"🏆 Overall ranking saved in {ranking_csv} and {ranking_excel}")


    def _generate_test_report(self):
        """Generate comprehensive test report"""
        analyzer = PerformanceAnalyzer(self.monitor_service)
        analyzer.analyze_all()
        
        # Generate visualizations
        self.visualization_engine.generate_all_plots(
            results = self.results_repository,
            analysis = analyzer.comparison_results
        )

class MPQUICTransferScenario:
    """Handles QUIC transfer scenarios and performance measurements"""
    
    def __init__(self, net, schedulers, framework, flow_types=['elephant', 'mice']):
        self.net = net
        self.schedulers = schedulers
        self.framework = framework
        self.flow_types = flow_types
        self.results = {
            'fat-tree': {flow: {} for flow in flow_types},
            'jellyfish': {flow: {} for flow in flow_types}
        }
        
    def setup_flow_parameters(self, flow_type):
        """Define parameters for different flow types"""
        if flow_type == 'elephant':
            return {
                'size': random.randint(100 * 1024 * 1024, 5 * 1024 * 1024 * 1024),  # 100MB to 5GB
                'priority': 1,
                'deadline': float('inf')
            }
        else:  # mice flow
            return {
                'size': random.randint(10 * 1024, 1 * 1024 * 1024),  # 10KB to 1MB
                'priority': 2,
                'deadline': 1.0  # 1 second deadline
            }
    
    

   

    def measure_performance(self, scheduler_name, flow_type):
        """Measure performance over 100 test runs and compute the average, including path efficiency."""
        total_time = []
        total_throughput = []
        total_packet_loss = []
        total_latency = []
        total_fairness = []
        total_path_efficiency = []

        for _ in range(100):  #  Run the test 100 times
            start_time = time.time()

            # ✅ Simulate realistic throughput, latency, and packet loss values
            throughput = random.uniform(50, 100)  # Mbps
            packet_loss = random.uniform(0.01, 5.0)  # Random loss between 0.01% and 5%

            # Compute scheduler-specific latency
            latency_values = [
                p.rtt * random.uniform(0.9, 1.1)  #  Slight randomness to avoid same values
                for p in self.schedulers[scheduler_name].paths.values()
            ]
            latency = np.mean(latency_values) if latency_values else 10  # Default 10ms if no data

            #  Calculate Fairness Index dynamically
            path_usage = {path.id: random.randint(1, 100) for path in self.schedulers[scheduler_name].paths.values()}
            fairness_index = self._calculate_fairness_index(path_usage)

            #  Compute Path Efficiency (Ensure Space After `)`)
            used_bandwidth = sum(
                p.bandwidth * random.uniform(0.6, 1.0) for p in self.schedulers[scheduler_name].paths.values()
            )
            total_available_bandwidth = sum(
                p.bandwidth for p in self.schedulers[scheduler_name].paths.values()
            )
            path_efficiency = (
                used_bandwidth / total_available_bandwidth if total_available_bandwidth > 0 else 0
            )

            # Store results for averaging later
            total_time.append(time.time() - start_time)
            total_throughput.append(throughput)
            total_packet_loss.append(packet_loss)
            total_latency.append(latency)
            total_fairness.append(fairness_index)
            total_path_efficiency.append(path_efficiency)

        # Compute averages after 100 runs
        return {
            'completion_time': np.mean(total_time),
            'throughput': np.mean(total_throughput),
            'packet_loss': np.mean(total_packet_loss),
            'latency': np.mean(total_latency),
            'fairness_index': np.mean(total_fairness),
            'path_efficiency': np.mean(total_path_efficiency)  # New metric added
        }

    def _configure_network(self, config: Dict):
        """Configure network conditions for schedulers based on test configuration"""
        try:
            for scheduler in self.schedulers.values():  # Iterate over schedulers
                for path in scheduler.paths.values():  # Access paths inside schedulers
                
                    # Set latency
                    if isinstance(config['latency'], list):
                        path.rtt = random.uniform(config['latency'][0], config['latency'][1])
                    elif isinstance(config['latency'], dict) and 'pattern' in config['latency']:
                        path.rtt = random.uniform(config['latency']['min'], config['latency']['max'])

                    # Set bandwidth
                    if isinstance(config['bandwidth'], list):
                        path.bandwidth = random.uniform(config['bandwidth'][0], config['bandwidth'][1])
                    elif isinstance(config['bandwidth'], dict) and 'pattern' in config['bandwidth']:
                        path.bandwidth = random.uniform(config['bandwidth']['min'], config['bandwidth']['max'])

                    # Set packet loss
                    if isinstance(config['loss'], list):
                        path.congestion_level = config['loss'][0] / 100.0
                    elif isinstance(config['loss'], dict) and 'pattern' in config['loss']:
                        path.congestion_level = random.uniform(config['loss']['min'], config['loss']['max']) / 100.0

                    # Configure cross traffic if enabled
                    if 'cross_traffic' in config and config['cross_traffic']['enabled']:
                        path.available_buffer *= (1 - config['cross_traffic']['intensity'])

        except Exception as e:
            print(f"Error configuring network: {str(e)}")

    def run_transfer_experiments(self, topology_type):
        """Run transfer experiments for each network condition separately."""
        print(f"\nRunning transfer experiments on {topology_type} topology...")

        hosts = self.net.hosts
        src_host = random.choice(hosts)
        dst_host = random.choice([h for h in hosts if h != src_host])

        for condition_name, config in self.framework.test_scenarios.items():  #  Loop through each condition
            print(f"\nApplying network condition: {condition_name}...")

            #  Reset results for this specific condition
            condition_results = {flow: {} for flow in self.flow_types}

            #  Apply the network settings for this condition
            self._configure_network(config)

            for flow_type in self.flow_types:
                print(f"\nTesting {flow_type} flows...")
                flow_params = self.setup_flow_parameters(flow_type)

                for scheduler_name in self.schedulers:
                    print(f"Testing {scheduler_name} scheduler...")
                    performance = self.measure_performance(scheduler_name, flow_type)
                    condition_results[flow_type][scheduler_name] = performance  #  Store per condition

            # Save results immediately for each condition
            self.framework.save_results(condition_results, condition_name, topology_type)

    
    def _calculate_path_efficiency(self, path_usage):
        """Calculate path efficiency based on usage"""
        # Example calculation: Jain's fairness index
        total_usage = sum(path_usage.values())
        if total_usage == 0:
            return 0.0
        
        fairness_index = (total_usage ** 2) / (len(path_usage) * sum(u ** 2 for u in path_usage.values()))
        return fairness_index

    
    def _ensure_4_paths(self, src_host, dst_host):
        """Ensure there are exactly 4 paths between the selected hosts"""
        # Get the network graph
        network_graph = self.net.topo.convert_to_nx_graph()
    
        # Debug: Print all nodes in the graph
        print("Nodes in the graph:", network_graph.nodes())
    
        # Debug: Print the source and destination hosts
        print(f"Source host: {src_host}, Destination host: {dst_host}")
    
        # Check if source and destination hosts exist in the graph
        if src_host not in network_graph:
            raise ValueError(f"Source host {src_host} not found in the graph")
        if dst_host not in network_graph:
            raise ValueError(f"Destination host {dst_host} not found in the graph")
    
        # Compute 4 shortest paths between the hosts
        try:
            paths = list(itertools.islice(nx.shortest_simple_paths(network_graph, src_host, dst_host), 4))
        except nx.NetworkXNoPath:
            raise ValueError(f"No path found between {src_host} and {dst_host}")
    
        if len(paths) < 4:
            raise ValueError(f"Less than 4 paths found between {src_host} and {dst_host}")
    
        # Assign the paths to the schedulers
        for scheduler in self.schedulers.values():
            scheduler.paths = {f"path{i}": PathState(
                id=f"path{i}",
                rtt=random.uniform(10, 100),  # Random RTT between 10ms and 100ms
                bandwidth=random.uniform(100, 1000),  # Random bandwidth between 100Mbps and 1Gbps
                cwnd=1000,
                congestion_level=random.uniform(0, 0.2),  # Random congestion level between 0% and 20%
                available_buffer=64000,
                in_recovery=False,
                last_sent_time=0.0
            ) for i in range(4)}
    def _calculate_fairness_index(self, path_usage):
        """Calculate Jain's Fairness Index for path usage"""
        import numpy as np  # Ensure NumPy is imported

        usage_values = np.array(list(path_usage.values()))
        n = len(usage_values)

        if n == 0 or np.sum(usage_values) == 0:
            return 0.0  # Return 0 if no paths are used

        fairness = (np.sum(usage_values) ** 2) / (n * np.sum(usage_values ** 2))
        return round(fairness, 4)  # Return fairness index rounded to 4 decimals
class VisualizationEngine:
    """Engine for generating visualizations of test results"""
    
    def __init__(self):
        self.style_config = {
            'figure.figsize': (12, 6),
            'axes.titlesize': 14,
            'axes.labelsize': 12,
            'lines.linewidth': 2,
            'lines.markersize': 8,
            'xtick.labelsize': 10,
            'ytick.labelsize': 10
        }
        self.color_palette = sns.color_palette("husl", 8)
        
    def generate_all_plots(self, results: Dict, analysis: Dict):
        """Generate all visualization plots"""
        try:
            plt.style.use('seaborn')
        except OSError:
            plt.style.use('default')  # Fallback to default matplotlib style
            
        for key, value in self.style_config.items():
            plt.rcParams[key] = value
            
        # Make sure to pass results to each plotting method
        self._plot_performance_comparison(results)
        self._plot_stability_analysis(analysis)
        self._plot_efficiency_metrics(analysis)
        self._generate_heatmap(results)
        self._plot_time_series(results)
        self._create_dashboard(results, analysis)
        
    def _plot_performance_comparison(self, results: Dict):
        """Plot performance comparison across schedulers"""
        plt.figure(figsize=(12, 6))
        
        # Get first network condition to get list of schedulers
        first_condition = list(results.keys())[0]
        metrics = ['latency', 'throughput', 'packet_loss', 'path_utilization']
        schedulers = list(results[first_condition].keys())
        
        x = np.arange(len(metrics))
        width = 0.8 / len(schedulers)
        
        for i, scheduler in enumerate(schedulers):
            values = []
            for metric in metrics:
                # Normalize metric values
                values.append(np.mean([
                    result[scheduler]['metrics'][metric]['mean']
                    for result in results.values()
                ]))
            
            plt.bar(x + i * width, values, width, 
                   label=scheduler, color=self.color_palette[i])
            
        plt.xlabel('Metrics')
        plt.ylabel('Normalized Value')
        plt.title('Performance Comparison Across Schedulers')
        plt.xticks(x + width * (len(schedulers) - 1) / 2, metrics)
        plt.legend()
        plt.tight_layout()
        plt.savefig('performance_comparison.png')
        plt.close()
            
    def _plot_stability_analysis(self, analysis: Dict):
        """Plot stability analysis results"""
        plt.figure(figsize=(10, 6))
        
        stability_data = analysis['stability_analysis']
        schedulers = list(stability_data.keys())
        metrics = ['throughput_stability', 'latency_stability', 'overall_stability']
        
        data = np.array([[stability_data[s][m] for m in metrics] for s in schedulers])
        
        sns.heatmap(data, annot=True, fmt='.2f', 
                   xticklabels=metrics, yticklabels=schedulers,
                   cmap='YlOrRd', center=0.5)
        
        plt.title('Stability Analysis Heatmap')
        plt.tight_layout()
        plt.savefig('stability_analysis.png')
        plt.close()
        
    def _plot_efficiency_metrics(self, analysis: Dict):
        """Plot efficiency metrics"""
        efficiency_data = analysis['efficiency_analysis']
        
        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(15, 6))
        
        # Path Efficiency
        schedulers = list(efficiency_data.keys())
        path_eff = [efficiency_data[s]['path_efficiency'] for s in schedulers]
        
        ax1.bar(schedulers, path_eff, color=self.color_palette)
        ax1.set_title('Path Efficiency')
        ax1.set_ylim(0, 1)
        ax1.tick_params(axis='x', rotation=45)
        
        # Resource Utilization
        resource_util = [efficiency_data[s]['resource_utilization'] 
                        for s in schedulers]
        
        ax2.bar(schedulers, resource_util, color=self.color_palette)
        ax2.set_title('Resource Utilization')
        ax2.set_ylim(0, 1)
        ax2.tick_params(axis='x', rotation=45)
        
        plt.tight_layout()
        plt.savefig('efficiency_metrics.png')
        plt.close()
        
    
    def _generate_heatmap(self, results: Dict):
        """Generate heatmap of performance across conditions"""
        # Get list of conditions and schedulers
        first_condition = list(results.keys())[0]
        conditions = list(results.keys())
        schedulers = list(results[first_condition].keys())
        
        data = np.zeros((len(schedulers), len(conditions)))
        
        for i, scheduler in enumerate(schedulers):
            for j, condition in enumerate(conditions):
                metrics = results[condition][scheduler]['metrics']
                
                # Handle division by zero for latency
                latency_score = 1 / metrics['latency']['mean'] if metrics['latency']['mean'] > 0 else 0
                
                score = (
                    latency_score * 0.3 +  # Lower latency is better
                    metrics['throughput']['mean'] * 0.3 +  # Higher throughput is better
                    (1 - metrics['packet_loss']['mean']) * 0.2 +  # Lower packet loss is better
                    metrics['path_utilization']['mean'] * 0.2  # Higher utilization is better
                )
                data[i, j] = score
        
        plt.figure(figsize=(12, 8))
        sns.heatmap(data, annot=True, fmt='.2f',
                   xticklabels=[c.value for c in conditions],
                   yticklabels=schedulers,
                   cmap='viridis')
        
        plt.title('Performance Heatmap Across Network Conditions')
        plt.tight_layout()
        plt.savefig('performance_heatmap.png')
        plt.close()
        
    def _plot_time_series(self, results: Dict):
        """Plot linear time series data for key metrics"""
        for condition in results.keys():
            condition_results = results[condition]
        
            fig, ax = plt.subplots(figsize=(15, 8))
            metrics = ['throughput', 'latency']  # Focus on key metrics
        
            for scheduler, data in condition_results.items():
                time_data = [m.timestamp for m in data['monitor_data']]
            
                for metric in metrics:
                    metric_data = [getattr(m, metric) for m in data['monitor_data']]
                    ax.plot(time_data, metric_data, 
                       label=f'{scheduler}-{metric}',
                       marker='o',
                       linestyle='-',
                       markersize=4)
                
        ax.set_xlabel('Time (s)')
        ax.set_ylabel('Metric Value')
        ax.set_title(f'Performance Metrics Over Time - {condition.value}')
        ax.grid(True)
        ax.legend()
        
        plt.tight_layout()
        plt.savefig(f'time_series_{condition.value}.png')
        plt.close()
        
    def _create_dashboard(self, results: Dict, analysis: Dict):
        """Create an HTML dashboard with all results"""
        html_content = self._generate_dashboard_html(results, analysis)
        
        with open('dashboard.html', 'w') as f:
            f.write(html_content)

    def _generate_dashboard_html(self, results: Dict, analysis: Dict) -> str:
        """Generate HTML content for dashboard"""
        # Previous implementation remains the same
        return f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>Multipath Scheduler Analysis Dashboard</title>
            <style>
                body {{ font-family: Arial, sans-serif; margin: 20px; }}
                .section {{ margin-bottom: 30px; }}
                .chart {{ margin: 20px 0; }}
                .metric-card {{ 
                    border: 1px solid #ddd; 
                    padding: 15px; 
                    margin: 10px; 
                    border-radius: 5px;
                }}
                .grid {{ 
                    display: grid;
                    grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
                    gap: 20px;
                }}
            </style>
        </head>
        <body>
            <h1>Multipath Scheduler Analysis Dashboard</h1>
            
            <div class="section">
                <h2>Performance Overview</h2>
                <div class="grid">
                    <div class="metric-card">
                        <img src="performance_comparison.png" width="100%">
                    </div>
                    <div class="metric-card">
                        <img src="performance_heatmap.png" width="100%">
                    </div>
                </div>
            </div>
            
            <div class="section">
                <h2>Stability Analysis</h2>
                <div class="grid">
                    <div class="metric-card">
                        <img src="stability_analysis.png" width="100%">
                    </div>
                    <div class="metric-card">
                        <img src="efficiency_metrics.png" width="100%">
                    </div>
                </div>
            </div>
            
            <div class="section">
                <h2>Time Series Analysis</h2>
                <div class="grid">
                    {self._generate_time_series_html(results)}
                </div>
            </div>
            
            <div class="section">
                <h2>Recommendations</h2>
                {self._generate_recommendations_html(analysis)}
            </div>
        </body>
        </html>
        """
        
    def _generate_time_series_html(self, results: Dict) -> str:
        """Generate HTML for time series charts"""
        html = ""
        for condition in results.keys():  # Changed from NetworkCondition to results.keys()
            html += f"""
                <div class="metric-card">
                    <h3>{condition.value}</h3>
                    <img src="time_series_{condition.value}.png" width="100%">
                </div>
            """
        return html
        
    def _generate_recommendations_html(self, analysis: Dict) -> str:
        """Generate HTML for recommendations section"""
        html = "<div class='grid'>"
        for scheduler, data in analysis['recommendations'].items():
            html += f"""
                <div class="metric-card">
                    <h3>{scheduler}</h3>
                    <h4>Strengths:</h4>
                    <ul>
                        {"".join(f"<li>{s}</li>" for s in data['strengths'])}
                    </ul>
                    <h4>Suggested Improvements:</h4>
                    <ul>
                        {"".join(f"<li>{s}</li>" for s in data['suggested_improvements'])}
                    </ul>
                    <h4>Best Use Cases:</h4>
                    <ul>
                        {"".join(f"<li>{s}</li>" for s in data['best_use_cases'])}
                    </ul>
                </div>
            """
        html += "</div>"
        return html
        
# MAIN Program Running
if __name__ == "__main__":
    setLogLevel('info')
    
    # Create schedulers with 4 paths
    schedulers = {
        "ECF": ECFScheduler(),
        "RR": RRScheduler(),
        "MPS_OF_AS": MPS_OF_ASScheduler(),
    }

    # Create monitoring services for each scheduler
    monitor_service = create_monitoring_service()

    # Set up test paths for each scheduler
    test_paths = create_test_environment()
    for scheduler in schedulers.values():
        scheduler.paths = test_paths

    # Initialize the test framework
    framework = NetworkTestFramework(schedulers, monitor_service)
    
    # Run comprehensive tests across all conditions
    framework.run_comprehensive_tests()

    print("Testing complete. Check the generated visualizations and reports.")
