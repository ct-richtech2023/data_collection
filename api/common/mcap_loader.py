import io
import threading
import time
import traceback
from threading import Thread

import av
import cv2
import numpy as np
from PyQt5.QtCore import QObject, pyqtSignal
from loguru import logger
from mcap.reader import make_reader
from mcap_protobuf.decoder import DecoderFactory

try:
    from common.schemas import TopicInfo, McapInfo, MetaData, Annotation
except ImportError:
    # 如果作为直接运行的脚本，使用相对导入
    from schemas import TopicInfo, McapInfo, MetaData, Annotation


class McapReader(QObject):
    # 信号定义
    frame_ready = pyqtSignal(object)  # 新帧准备好的信号 (VideoFrame)
    playback_finished = pyqtSignal()  # 播放完成信号
    fps_detected = pyqtSignal(int)  # FPS检测完成信号
    annotation_loaded = pyqtSignal(object)  # 注释加载信号

    def __init__(self, mcap_path: str, cache_count=300):
        super().__init__()
        # 基本参数
        self.mcap_path = mcap_path
        self.is_playing = False
        self.play_speed = 1.0  # 播放倍速
        self.max_cache_count = cache_count
        self.tolerance_ns = 3 * 1e6  # 3ms容差, 3ms以内的数据被认为是同一时刻的帧数据
        self.cache_start: int = 0
        self.cache_end = 0
        self.next_load_count = max(int(self.max_cache_count * 0.3), 1)
        self.load_thread = None
        self.stop_load = threading.Event()
        self.sync_lock = threading.Lock()
        self.target_frame = 0

        # 视频参数-从mcap获取
        self.video_topics = []
        self.calibration_topics = []
        self.synchronized_frames = {}  # 替代原来的 frame_cache {frame_index: {topic: frame}}
        self.index_time_dict = {} # {id: timestamp}
        self.current_frame_index = 0  # 当前播放位置
        self.fps = 0
        self.file_info: McapInfo = None

        self.get_file_info()

    def get_file_info(self):
        with open(self.mcap_path, "rb") as f:
            reader = make_reader(f)
            summary = reader.get_summary()
            start_time_ns = summary.statistics.message_start_time or 0
            end_time_ns = summary.statistics.message_end_time or 0
            duration_sec = (end_time_ns - start_time_ns) / 1e9

            topics_infos = []
            min_video_count = None
            for i, channel in summary.channels.items():
                msg_count = summary.statistics.channel_message_counts[i]
                protobuf_class = summary.schemas[i].name
                fps = 0
                if msg_count > 1:
                    fps = round(summary.statistics.channel_message_counts[i] / duration_sec, 2)
                logger.info(f"topic: {channel.topic}; fps: {fps}; class name: {protobuf_class}")

                if protobuf_class in ['foxglove.RawImage', 'foxglove.CompressedVideo']:
                    if channel.topic not in ['/camera/depth/depth']:
                        self.video_topics.append(channel.topic)
                        logger.info(f"fps update from {self.fps} to {fps} ")
                        self.fps = fps
                        if min_video_count is None or msg_count < min_video_count:
                            min_video_count = msg_count
                elif protobuf_class in ['foxglove.CameraCalibration', 'robot_data.CameraParameters']:
                    self.calibration_topics.append(channel.topic)

                topic_info = TopicInfo(topic=channel.topic, msg_count=msg_count, fps=fps)
                topics_infos.append(topic_info)

            # 加载现有注释
            logger.info('loading annotations start...')
            annotations = self._load_annotations()
            logger.info(f"annotations: {annotations}")
            logger.info('loading annotations end...')

            # 加载原有元数据
            metadata = self._load_metadata()

            file_info = McapInfo(start_ns=start_time_ns, end_ns=end_time_ns, duration_sec=duration_sec,
                                 topic_infos=topics_infos, video_topics=self.video_topics.copy(),
                                 calibration_topics=self.calibration_topics.copy(), video_fps=self.fps,
                                 video_frame_count=min_video_count - 1, annotations=annotations, metadata=metadata)
            self.file_info = file_info
            # logger.info(f"file_info: {file_info}")
        return file_info

    def _load_annotations(self):
        """从MCAP文件中加载现有注释"""
        annotations = []
        try:
            with open(self.mcap_path, "rb") as f:
                reader = make_reader(f, decoder_factories=[DecoderFactory()])
                for schema, channel, message, proto_msg in reader.iter_decoded_messages(topics=['/subtask-annotation']):
                    # 假设注释消息有text字段  todo
                    annotation = Annotation(
                        timestamp_ns=message.log_time,
                        text=proto_msg.data
                    )
                    annotations.append(annotation)
                    logger.info(f"加载注释:  at {message.log_time}")
        except Exception as e:
            logger.error(traceback.format_exc())
            logger.warning(f"加载注释失败: {e}")

        return annotations

    def _load_metadata(self):
        try:
            with open(self.mcap_path, "rb") as f:
                reader = make_reader(f)
                metadata_dict = {}
                for metadata in reader.iter_metadata():
                    # logger.info(f"Metadata '{metadata.name}': {metadata.metadata}")
                    metadata_dict.update(metadata.metadata)
                if metadata_dict:
                    metadata = MetaData(uuid=metadata_dict.get('session-metadata.session-uuid'), operator_name=metadata_dict.get('session-metadata.operator-id'),
                                        station_id=metadata_dict.get('session-metadata.station_id'),
                                        task_command=metadata_dict.get('session-metadata.instruction'))
                    return metadata
        except Exception as e:
            logger.warning(f"加载元数据失败: {e}")
            logger.error(traceback.format_exc())

    def _process_video_message(self, schema, channel, message, proto_msg):
        img = None
        # 使用schema.name判断消息类型，而不是isinstance
        schema_name = schema.name
        
        if schema_name == 'foxglove.RawImage':
            height, width, encoding = proto_msg.height, proto_msg.width, proto_msg.encoding
            data = proto_msg.data
            img_array = np.frombuffer(data, dtype=np.uint8)
            # 解码图像数据
            if encoding.lower() == "rgb8":
                img = img_array.reshape((height, width, 3))
                img = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)
            elif encoding.lower() == "bgr8":
                img = img_array.reshape((height, width, 3))
            elif encoding.lower() == "mono8":
                img = img_array.reshape((height, width))
            else:
                logger.warning(f"unknown encoding {encoding.lower()}")
        elif schema_name == 'foxglove.CompressedVideo':
            # 处理压缩视频 - 需要解压缩
            format_lower = proto_msg.format.lower()
            if format_lower == 'h264':
                try:
                    # 使用 PyAV 解码 H.264 字节流
                    container = av.open(io.BytesIO(proto_msg.data), format='h264')
                    for frame in container.decode(video=0):
                        img = frame.to_ndarray(format='bgr24')
                        break  # 只取第一个解码帧
                except Exception as e:
                    logger.error(f"H264 解码失败: {e}")
                    img = None
            else:
                logger.warning(f"不支持的压缩视频格式: {proto_msg.format}")
        else:
            logger.warning(f"未知的视频消息类型: {schema_name}")
        
        return img

    def load_frames(self, start_ns=None, end_ns=None, start_frame=0):
        current_group = {}  # {topic: frame}
        current_base_time = None
        frame_index = start_frame
        self.synchronized_frames.clear()
        self.cache_start = None
        with open(self.mcap_path, "rb") as f:
            logger.info('start loading...')
            reader = make_reader(f, decoder_factories=[DecoderFactory()])
            self.sync_lock.acquire(timeout=1)
            try:
                for schema, channel, message, proto_msg in reader.iter_decoded_messages(topics=self.video_topics + ['/annotations'],
                                                                                        start_time=start_ns,
                                                                                        end_time=end_ns):
                    if self.stop_load.is_set():
                        logger.info('stop loading...')
                        break
                    frame = self._process_video_message(schema, channel, message, proto_msg)
                    timestamp = message.log_time
                    topic = channel.topic

                    if current_base_time is None or abs(timestamp - current_base_time) > self.tolerance_ns:
                        # 保存当前帧组
                        if current_group:
                            self.synchronized_frames[frame_index] = {'timestamp': current_base_time,
                                                                     'topics': current_group.copy()}
                            self.index_time_dict[frame_index] = current_base_time
                            self.cache_end = frame_index
                            if self.cache_start is None:
                                self.cache_start = frame_index
                            if frame_index % 30 == 0:
                                logger.debug(f'loaded frame {frame_index}')
                            frame_index += 1
                        # 开始新帧组
                        current_base_time = timestamp
                        current_group = {topic: frame}
                    else:
                        current_group[topic] = frame

                    need_release_index = max(frame_index - self.next_load_count, 0)

                    # if self.current_frame_index > need_release_index and need_release_index > self.cache_start:
                    #     logger.debug(f'clear frame from {self.cache_start} to {need_release_index}')
                    #     for i in range(self.cache_start, need_release_index):
                    #         self.synchronized_frames.pop(i, None)
                    #     self.cache_start = need_release_index

                    # 控制缓存大小
                    while not self.stop_load.is_set() and len(self.synchronized_frames) >= self.max_cache_count:
                        # 缓存满了以后才考虑清空
                        if self.target_frame > 0 and self.target_frame >= self.cache_end:
                            # 如果向后跳转很多，就一直清空
                            for i in range(self.cache_start, frame_index):
                                logger.debug(f'clear frame1 from {self.cache_start} to {need_release_index}')
                                self.synchronized_frames.pop(i, None)
                            self.cache_start = frame_index
                        if self.current_frame_index > need_release_index:
                            # 如果正常播放，到了清缓存程度，就清空最前面0.2的数量
                            clear_to = self.cache_start + self.next_load_count
                            logger.debug(f'clear frame2 from {self.cache_start} to {clear_to}')
                            for i in range(self.cache_start, clear_to):
                                self.synchronized_frames.pop(i, None)
                            self.cache_start = clear_to
                        time.sleep(0.02)
            finally:
                self.sync_lock.release()
        logger.info('finished loading, release lock')

    def start_load_video(self, start_ns=None, end_ns=None, start_frame=0):
        logger.debug(f'start load video from {self.mcap_path}')
        self.load_thread = Thread(target=self.load_frames, args=(start_ns, end_ns, start_frame), daemon=True)
        self.load_thread.start()


    def get_next_frame(self):
        """获取下一帧数据"""
        logger.debug(f'get_next_frame: {self.current_frame_index}')
        while self.cache_start is None:
            time.sleep(0.1)
        if self.cache_start <= self.current_frame_index <= self.cache_end:
            frame = self.synchronized_frames[self.current_frame_index]
            self.current_frame_index += 1
            return frame

        logger.warning('next frame not in cache')
        return None

    def seek_to_frame_index(self, frame_index):
        """跳转到指定帧索引"""
        try:
            logger.debug(f'seek_to_frame_index: {frame_index}')
            self.target_frame = frame_index
            if self.cache_start <= frame_index < self.cache_end:
                self.current_frame_index = frame_index + 1
                return self.synchronized_frames[frame_index]
            else:
                logger.warning('next frame not in cache, need reload')
                start_ts = self.index_time_dict.get(frame_index)
                if start_ts is not None:
                    self._safe_stop_and_restart(start_ts, frame_index)
                else:
                    logger.info(f'waiting for loading to {frame_index}')

                while frame_index not in self.synchronized_frames:
                    time.sleep(0.01)
                self.current_frame_index = frame_index + 1
                return self.synchronized_frames[frame_index]
        except Exception as e:
            logger.error(traceback.format_exc())
        return None

    def _safe_stop_and_restart(self, start_ts, target_frame):
        """安全地停止当前加载并重新开始"""
        # 1. 设置停止标志
        logger.debug(f'_safe_stop_and_restart: {start_ts}, {target_frame}')
        self.stop_load.set()
        if self.load_thread and self.load_thread.is_alive():
            self.load_thread.join(timeout=1.0)  # 增加到1秒

            if self.load_thread.is_alive():
                logger.warning("加载线程未能在1秒内停止，强制继续")

        # 4. 重新开始加载
        self.stop_load.clear()
        self.start_load_video(start_ts, start_frame=target_frame)

    def get_index_by_time(self, time_ns):
        if self.cache_start is not None and self.cache_end is not None:
            max_recorded_ns = max(self.index_time_dict.values())
            if time_ns > max_recorded_ns:
                self.target_frame = self.file_info.video_frame_count - 1

            target_index = min(self.index_time_dict, key=lambda k: abs(self.index_time_dict[k] - time_ns))
            return target_index
        else:
            logger.warning(f'还没有开始加载数据呢')

    def close(self):
        logger.debug(f'close')
        self.stop_load.set()
        self.synchronized_frames.clear()

if __name__ == '__main__':
    import sys
    import os
    # 添加项目根目录到 Python 路径
    current_dir = os.path.dirname(os.path.abspath(__file__))
    api_dir = os.path.dirname(current_dir)
    sys.path.insert(0, api_dir)
    
    mcap_loader = McapReader('api/uploads/2dc1c319-c3c9-4828-bd17-7ed5ac7ea105.mcap')
    file_info = mcap_loader.file_info
    logger.info(f"文件信息验证:")
    logger.info(f"  - 时长: {file_info.duration_sec:.2f}秒")
    logger.info(f"  - 视频帧数: {file_info.video_frame_count}")
    logger.info(f"  - FPS: {file_info.video_fps}")
    logger.info(f"  - 视频topics: {file_info.video_topics}")
    logger.info(f"  - 标定topics: {file_info.calibration_topics}")
    logger.info(f"  - 注释数量: {len(file_info.annotations)}")
    logger.info(f"  - 元数据: {file_info.metadata}")