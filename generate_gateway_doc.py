#!/usr/bin/env python3
"""生成 Gateway C++ 数据交互逻辑 PDF 文档"""

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm, cm
from reportlab.lib.colors import HexColor, black, white
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_JUSTIFY
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    PageBreak, ListFlowable, ListItem, HRFlowable, KeepTogether
)
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
import os

def create_pdf(output_path):
    """创建 PDF 文档"""
    
    # 注册中文字体（使用系统字体）
    font_paths = [
        '/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc',
        '/usr/share/fonts/truetype/wqy/wqy-microhei.ttc',
        '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc',
    ]
    
    font_path = None
    for path in font_paths:
        if os.path.exists(path):
            font_path = path
            break
    
    if font_path:
        pdfmetrics.registerFont(TTFont('SimSun', font_path))
        pdfmetrics.registerFont(TTFont('SimSun-Bold', font_path))
    else:
        print("警告: 未找到中文字体，将使用默认字体")
    
    # 创建文档
    doc = SimpleDocTemplate(
        output_path,
        pagesize=A4,
        leftMargin=2*cm,
        rightMargin=2*cm,
        topMargin=2*cm,
        bottomMargin=2*cm,
        title="Gateway 数据交互逻辑说明文档",
        author="SIM Platform Team"
    )
    
    story = []
    
    # 样式定义
    styles = getSampleStyleSheet()
    
    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Title'],
        fontSize=24,
        spaceAfter=10*mm,
        alignment=TA_CENTER,
        textColor=HexColor('#1a5276'),
        fontName='SimSun-Bold' if font_path else 'Helvetica-Bold'
    )
    
    heading1_style = ParagraphStyle(
        'Heading1Custom',
        parent=styles['Heading1'],
        fontSize=18,
        spaceBefore=12*mm,
        spaceAfter=6*mm,
        textColor=HexColor('#2874a6'),
        fontName='SimSun-Bold' if font_path else 'Helvetica-Bold'
    )
    
    heading2_style = ParagraphStyle(
        'Heading2Custom',
        parent=styles['Heading2'],
        fontSize=14,
        spaceBefore=8*mm,
        spaceAfter=4*mm,
        textColor=HexColor('#5dade2'),
        fontName='SimSun-Bold' if font_path else 'Helvetica-Bold'
    )
    
    heading3_style = ParagraphStyle(
        'Heading3Custom',
        parent=styles['Heading3'],
        fontSize=12,
        spaceBefore=6*mm,
        spaceAfter=3*mm,
        textColor=HexColor('#3498db'),
        fontName='SimSun-Bold' if font_path else 'Helvetica-Bold'
    )
    
    body_style = ParagraphStyle(
        'BodyCustom',
        parent=styles['Normal'],
        fontSize=10,
        spaceAfter=3*mm,
        alignment=TA_JUSTIFY,
        leading=16,
        fontName='SimSun' if font_path else 'Helvetica'
    )
    
    code_style = ParagraphStyle(
        'CodeBlock',
        parent=styles['Normal'],
        fontSize=9,
        fontName='Courier',
        leftIndent=10*mm,
        rightIndent=5*mm,
        spaceBefore=3*mm,
        spaceAfter=3*mm,
        leading=13,
        textColor=HexColor('#c0392b')
    )
    
    bullet_style = ParagraphStyle(
        'BulletCustom',
        parent=styles['Normal'],
        fontSize=10,
        leftIndent=8*mm,
        spaceAfter=2*mm,
        leading=14,
        fontName='SimSun' if font_path else 'Helvetica'
    )
    
    # ========== 封面 ==========
    story.append(Spacer(1, 60*mm))
    story.append(Paragraph("Gateway 数据交互逻辑", title_style))
    story.append(Paragraph("系统层面详细说明文档", ParagraphStyle(
        'Subtitle', parent=title_style, fontSize=16, textColor=HexColor('#7f8c8d')
    )))
    story.append(Spacer(1, 20*mm))
    
    # 封面信息表格
    info_data = [
        ['项目名称', '矿用卡车仿真平台'],
        ['模块名称', 'Gateway (C++)'],
        ['文档版本', 'v1.0'],
        ['生成日期', '2026-05-28'],
        ['文档作者', 'SIM Platform Team'],
    ]
    
    info_table = Table(info_data, colWidths=[4*cm, 10*cm])
    info_table.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (-1, -1), 'SimSun' if font_path else 'Helvetica'),
        ('FONTSIZE', (0, 0), (-1, -1), 11),
        ('ALIGN', (0, 0), (0, -1), 'RIGHT'),
        ('ALIGN', (1, 0), (1, -1), 'LEFT'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING', (0, 0), (-1, -1), 8),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
        ('BACKGROUND', (0, 0), (0, -1), HexColor('#eaf2f8')),
        ('TEXTCOLOR', (0, 0), (0, -1), HexColor('#1a5276')),
        ('GRID', (0, 0), (-1, -1), 0.5, HexColor('#aed6f1')),
        ('BOX', (0, 0), (-1, -1), 1, HexColor('#2874a6')),
    ]))
    story.append(info_table)
    
    story.append(PageBreak())
    
    # ========== 目录 ==========
    story.append(Paragraph("目录", heading1_style))
    story.append(HRFlowable(width="100%", thickness=1, color=HexColor('#2874a6')))
    story.append(Spacer(1, 5*mm))
    
    toc_items = [
        "1. 系统架构概述",
        "2. 核心组件说明",
        "3. MQTT 通信机制",
        "4. 云端数据交互流程",
        "5. DDS 进程间通信",
        "6. 定时任务管理",
        "7. 文件下载与处理",
        "8. 数据流全景图",
        "9. 关键数据结构",
        "10. 错误处理机制"
    ]
    
    for item in toc_items:
        story.append(Paragraph(item, ParagraphStyle(
            'TOC', parent=body_style, fontSize=11, spaceAfter=3*mm,
            fontName='SimSun-Bold' if font_path else 'Helvetica-Bold'
        )))
    
    story.append(PageBreak())
    
    # ========== 1. 系统架构概述 ==========
    story.append(Paragraph("1. 系统架构概述", heading1_style))
    story.append(HRFlowable(width="100%", thickness=1, color=HexColor('#2874a6')))
    story.append(Spacer(1, 3*mm))
    
    story.append(Paragraph(
        "Gateway 模块是矿用卡车仿真平台的核心通信网关，负责车端与云端之间的数据交互。",
        body_style
    ))
    story.append(Paragraph("主要职责包括:", body_style))
    
    responsibilities = [
        "通过 MQTT 协议与云端服务器（MineServer）进行远程通信",
        "通过 DDS（FastDDS）与本地感知、规划、控制模块进行进程间通信",
        "处理云端下发的任务调度、路权指令、参数查询等消息",
        "周期性上报车辆位置、状态、监控数据到云端",
        "从云端下载任务文件和地图文件并分发给规划模块"
    ]
    
    for resp in responsibilities:
        story.append(Paragraph(f"  - {resp}", bullet_style))
    
    story.append(Spacer(1, 5*mm))
    story.append(Paragraph("系统架构图:", body_style))
    
    # 架构描述表格
    arch_data = [
        ['层级', '组件', '协议/技术', '说明'],
        ['云端层', 'MineServer', 'MQTT + HTTP', '任务调度、参数管理'],
        ['网关层', 'Gateway (C++)', 'MQTT + DDS', '数据路由、协议转换'],
        ['车端层', 'Planning/Control', 'DDS (FastDDS)', '路径规划、车辆控制'],
        ['感知层', 'Perception', 'DDS (FastDDS)', '障碍物检测、环境感知'],
    ]
    
    arch_table = Table(arch_data, colWidths=[2*cm, 3.5*cm, 3.5*cm, 5*cm])
    arch_table.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (-1, -1), 'SimSun' if font_path else 'Helvetica'),
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('BACKGROUND', (0, 0), (-1, 0), HexColor('#2874a6')),
        ('TEXTCOLOR', (0, 0), (-1, 0), white),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('GRID', (0, 0), (-1, -1), 0.5, HexColor('#aed6f1')),
        ('BOX', (0, 0), (-1, -1), 1, HexColor('#2874a6')),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [white, HexColor('#eaf2f8')]),
    ]))
    story.append(arch_table)
    
    story.append(PageBreak())
    
    # ========== 2. 核心组件说明 ==========
    story.append(Paragraph("2. 核心组件说明", heading1_style))
    story.append(HRFlowable(width="100%", thickness=1, color=HexColor('#2874a6')))
    story.append(Spacer(1, 3*mm))
    
    story.append(Paragraph("2.1 GateWay 主类", heading2_style))
    story.append(Paragraph(
        "GateWay 类是整个网关模块的核心，封装了所有通信逻辑和数据处理流程。",
        body_style
    ))
    
    story.append(Paragraph("关键成员变量:", heading3_style))
    
    member_vars = [
        "mqtt_client_: MQTT 客户端实例，负责与云端的双向通信",
        "authentication_flag_: 鉴权状态标志，确保只有鉴权成功后才发送数据",
        "mqtt_connect_flag_: MQTT 连接状态标志",
        "deal_cloudmsg_map_: 云端消息处理函数映射表",
        "periodic_funs_1s / periodic_funs_10s: 定时任务函数列表",
        "project_id_: 从鉴权结果获取的项目 ID，用于文件下载鉴权",
        "imei_: 设备唯一标识，用于 MQTT Topic 构建"
    ]
    
    for var in member_vars:
        story.append(Paragraph(f"  - {var}", bullet_style))
    
    story.append(Spacer(1, 3*mm))
    story.append(Paragraph("2.2 MQTTGenericClient 类", heading2_style))
    story.append(Paragraph(
        "泛型 MQTT 客户端，支持任意 Protobuf 消息类型的发布和订阅。",
        body_style
    ))
    
    story.append(Paragraph("核心特性:", heading3_style))
    
    mqtt_features = [
        "模板化设计：支持任意 Protobuf 消息类型",
        "自动序列化/反序列化：使用 ParseFromString 和 SerializeToString",
        "异步连接：支持自动重连机制",
        "回调机制：消息到达时自动触发注册的回调函数",
        "类型安全：使用 std::any 和 std::type_index 保证类型匹配"
    ]
    
    for feature in mqtt_features:
        story.append(Paragraph(f"  - {feature}", bullet_style))
    
    story.append(Spacer(1, 3*mm))
    story.append(Paragraph("2.3 HttpDownloader 类", heading2_style))
    story.append(Paragraph(
        "基于 libcurl 的 HTTP 文件下载器，用于从云端下载任务文件和地图文件。",
        body_style
    ))
    
    story.append(Paragraph("功能特点:", heading3_style))
    
    http_features = [
        "支持自定义 HTTP 请求头（timestamp、sign、projectid）",
        "MD5 签名验证：sign = md5('crccAuthentication' + timestamp)",
        "支持断点续传",
        "支持下载进度回调",
        "超时控制"
    ]
    
    for feature in http_features:
        story.append(Paragraph(f"  - {feature}", bullet_style))
    
    story.append(PageBreak())
    
    # ========== 3. MQTT 通信机制 ==========
    story.append(Paragraph("3. MQTT 通信机制", heading1_style))
    story.append(HRFlowable(width="100%", thickness=1, color=HexColor('#2874a6')))
    story.append(Spacer(1, 3*mm))
    
    story.append(Paragraph("3.1 连接建立流程", heading2_style))
    
    story.append(Paragraph("MQTT 连接步骤:", body_style))
    
    connect_steps = [
        "从配置文件 gateway_config.ini 读取 broker 地址、用户名、密码",
        "创建 MQTTGenericClient 实例，client_id = 前缀 + imei",
        "启动独立线程执行连接逻辑（thread_mqtt_connect_）",
        "循环尝试连接，失败后等待 10 秒重试",
        "连接成功后订阅 3 个下行 Topic"
    ]
    
    for i, step in enumerate(connect_steps, 1):
        story.append(Paragraph(f"{i}. {step}", bullet_style))
    
    story.append(Spacer(1, 3*mm))
    story.append(Paragraph("订阅的 Topic 列表:", heading3_style))
    
    topic_data = [
        ['Topic 名称', 'QoS', '用途'],
        ['down/truck/{imei}', '1', '接收云端常规消息'],
        ['/retain/down/status/truck/{imei}', '1', '接收车辆状态指令（保留消息）'],
        ['/retain/down/dispatch/task/truck/{imei}', '1', '接收任务调度指令（保留消息）'],
    ]
    
    topic_table = Table(topic_data, colWidths=[5*cm, 1.5*cm, 7*cm])
    topic_table.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (-1, -1), 'SimSun' if font_path else 'Helvetica'),
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('BACKGROUND', (0, 0), (-1, 0), HexColor('#2874a6')),
        ('TEXTCOLOR', (0, 0), (-1, 0), white),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('GRID', (0, 0), (-1, -1), 0.5, HexColor('#aed6f1')),
        ('BOX', (0, 0), (-1, -1), 1, HexColor('#2874a6')),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [white, HexColor('#eaf2f8')]),
    ]))
    story.append(topic_table)
    
    story.append(Spacer(1, 5*mm))
    story.append(Paragraph("3.2 上行 Topic", heading2_style))
    story.append(Paragraph(
        "所有上行消息统一发布到: up/truck/{imei}",
        body_style
    ))
    
    story.append(Spacer(1, 3*mm))
    story.append(Paragraph("3.3 消息格式", heading2_style))
    story.append(Paragraph(
        "所有 MQTT 消息使用 Protobuf 序列化，主要消息类型包括:",
        body_style
    ))
    
    msg_types = [
        "DeviceMsg: 车端上行消息（位置、状态、监控、障碍物）",
        "CloudMsg: 云端下行消息（鉴权、任务、路权、参数）"
    ]
    
    for msg in msg_types:
        story.append(Paragraph(f"  - {msg}", bullet_style))
    
    story.append(PageBreak())
    
    # ========== 4. 云端数据交互流程 ==========
    story.append(Paragraph("4. 云端数据交互流程", heading1_style))
    story.append(HRFlowable(width="100%", thickness=1, color=HexColor('#2874a6')))
    story.append(Spacer(1, 3*mm))
    
    story.append(Paragraph("4.1 鉴权流程", heading2_style))
    story.append(Paragraph(
        "鉴权是系统初始化的第一步，只有鉴权成功后才能进行后续通信。",
        body_style
    ))
    
    story.append(Paragraph("鉴权步骤:", heading3_style))
    
    auth_steps = [
        "等待 MQTT 连接成功（mqtt_connect_flag_ = true）",
        "构造 DeviceMsg 消息，设置 authentication.authCode = imei_",
        "发布到 Topic: up/truck/{imei}",
        "每 5 秒发送一次，直到收到成功响应",
        "云端返回 AuthenticationApply 消息，resultCode = 0 表示成功",
        "设置 authentication_flag_ = true，记录 project_id_"
    ]
    
    for i, step in enumerate(auth_steps, 1):
        story.append(Paragraph(f"{i}. {step}", bullet_style))
    
    story.append(Spacer(1, 3*mm))
    story.append(Paragraph("关键代码片段:", heading3_style))
    story.append(Paragraph(
        "device.mutable_authentication()->set_authcode(imei_);",
        code_style
    ))
    story.append(Paragraph(
        "mqtt_client_->publish(\"up/truck/\" + imei_, device);",
        code_style
    ))
    
    story.append(Spacer(1, 5*mm))
    story.append(Paragraph("4.2 服务器参数查询", heading2_style))
    story.append(Paragraph(
        "鉴权成功后，立即发送服务器参数查询请求，获取地图文件信息和下载地址。",
        body_style
    ))
    
    story.append(Paragraph("查询参数:", heading3_style))
    
    params_list = [
        "0xF000: 地图文件名称（map_file_name）",
        "0xF001: 地图文件 MD5 校验值",
        "0xF002: 文件下载服务地址（base_url）"
    ]
    
    for param in params_list:
        story.append(Paragraph(f"  - {param}", bullet_style))
    
    story.append(Spacer(1, 5*mm))
    story.append(Paragraph("4.3 任务调度流程", heading2_style))
    story.append(Paragraph("云端下发任务调度的完整流程:", body_style))
    
    task_steps = [
        "云端发送 DispatchTask 消息到 /retain/down/dispatch/task/truck/{imei}",
        "Gateway 收到消息后检查 dispatch_result，失败则记录日志并返回",
        "提取任务文件名（command.path）和 MD5（command.fileMd5）",
        "启动独立线程下载任务文件（tar.gz 格式）",
        "下载成功后解压文件到指定目录",
        "使用 TrajParser 解析轨迹数据",
        "构造 TaskToPlanning 消息，通过 DDS 发布到规划模块"
    ]
    
    for i, step in enumerate(task_steps, 1):
        story.append(Paragraph(f"{i}. {step}", bullet_style))
    
    story.append(PageBreak())
    
    # ========== 5. DDS 进程间通信 ==========
    story.append(Paragraph("5. DDS 进程间通信", heading1_style))
    story.append(HRFlowable(width="100%", thickness=1, color=HexColor('#2874a6')))
    story.append(Spacer(1, 3*mm))
    
    story.append(Paragraph("5.1 DDS 订阅者", heading2_style))
    story.append(Paragraph("Gateway 订阅以下 DDS Topic 接收车端内部模块数据:", body_style))
    
    dds_sub_data = [
        ['Topic 名称', '消息类型', '用途'],
        ['fusion_front_scatter_box_/v1', 'DDS_SensorFuseResults', '接收前方感知障碍物数据'],
        ['sub_localization', 'common::Localization', '接收车辆定位数据'],
        ['sub_chassis', 'canbus::Chassis', '接收底盘状态数据'],
    ]
    
    dds_sub_table = Table(dds_sub_data, colWidths=[4.5*cm, 4*cm, 5.5*cm])
    dds_sub_table.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (-1, -1), 'SimSun' if font_path else 'Helvetica'),
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('BACKGROUND', (0, 0), (-1, 0), HexColor('#2874a6')),
        ('TEXTCOLOR', (0, 0), (-1, 0), white),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('GRID', (0, 0), (-1, -1), 0.5, HexColor('#aed6f1')),
        ('BOX', (0, 0), (-1, -1), 1, HexColor('#2874a6')),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [white, HexColor('#eaf2f8')]),
    ]))
    story.append(dds_sub_table)
    
    story.append(Spacer(1, 5*mm))
    story.append(Paragraph("5.2 DDS 发布者", heading2_style))
    story.append(Paragraph("Gateway 发布以下 DDS Topic 向车端内部模块发送数据:", body_style))
    
    dds_pub_data = [
        ['Topic 名称', '消息类型', '用途'],
        ['pub_task', 'gateway::TaskToPlanning', '向规划模块下发任务轨迹'],
        ['pub_move_authority', 'MovemntAuthoritySend', '向规划模块下发路权信息'],
    ]
    
    dds_pub_table = Table(dds_pub_data, colWidths=[4.5*cm, 4*cm, 5.5*cm])
    dds_pub_table.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (-1, -1), 'SimSun' if font_path else 'Helvetica'),
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('BACKGROUND', (0, 0), (-1, 0), HexColor('#2874a6')),
        ('TEXTCOLOR', (0, 0), (-1, 0), white),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('GRID', (0, 0), (-1, -1), 0.5, HexColor('#aed6f1')),
        ('BOX', (0, 0), (-1, -1), 1, HexColor('#2874a6')),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [white, HexColor('#eaf2f8')]),
    ]))
    story.append(dds_pub_table)
    
    story.append(Spacer(1, 5*mm))
    story.append(Paragraph("5.3 障碍物数据上报流程", heading2_style))
    story.append(Paragraph("当感知模块检测到前方障碍物时:", body_style))
    
    obstacle_steps = [
        "Perception 模块发布 DDS_SensorFuseResults 到 DDS",
        "Gateway 的 recvPerceptionFrontMsg 回调被触发",
        "提取障碍物包围盒的 4 个角点坐标",
        "将相对坐标转换为全局经纬度坐标（Tools::relativeToGlobal）",
        "构造 StopObstacleInfo Protobuf 消息",
        "通过 MQTT 发布到 up/truck/{imei}"
    ]
    
    for i, step in enumerate(obstacle_steps, 1):
        story.append(Paragraph(f"{i}. {step}", bullet_style))
    
    story.append(PageBreak())
    
    # ========== 6. 定时任务管理 ==========
    story.append(Paragraph("6. 定时任务管理", heading1_style))
    story.append(HRFlowable(width="100%", thickness=1, color=HexColor('#2874a6')))
    story.append(Spacer(1, 3*mm))
    
    story.append(Paragraph("6.1 定时任务调度器", heading2_style))
    story.append(Paragraph(
        "Gateway 使用补偿式定时任务调度器，避免任务执行耗时导致的定时漂移。",
        body_style
    ))
    
    story.append(Paragraph("调度策略:", heading3_style))
    story.append(Paragraph(
        "记录上次执行时间 last_time，每次执行后计算实际耗时，",
        body_style
    ))
    story.append(Paragraph(
        "休眠时间 = 周期 - 执行耗时。如果执行耗时超过周期，则立即执行下次任务。",
        body_style
    ))
    
    story.append(Spacer(1, 3*mm))
    story.append(Paragraph("6.2 1 秒周期任务", heading2_style))
    
    task_1s = [
        "sendVehiclePositionToCloud(): 上报车辆位置信息（经纬度、航向角、速度等）",
        "sendVehicleMonitorToCloud(): 上报车辆监控数据（油门、制动、转速等）"
    ]
    
    for task in task_1s:
        story.append(Paragraph(f"  - {task}", bullet_style))
    
    story.append(Spacer(1, 3*mm))
    story.append(Paragraph("6.3 10 秒周期任务", heading2_style))
    story.append(Paragraph("  - sendVehicleStatusToCloud(): 上报车辆状态（机油压力、冷却液温度、电池电压等）", bullet_style))
    
    story.append(Spacer(1, 3*mm))
    story.append(Paragraph("6.4 5 秒周期任务（仿真数据）", heading2_style))
    story.append(Paragraph("  - simulationData(): 生成模拟的位置数据用于测试", bullet_style))
    
    story.append(PageBreak())
    
    # ========== 7. 文件下载与处理 ==========
    story.append(Paragraph("7. 文件下载与处理", heading1_style))
    story.append(HRFlowable(width="100%", thickness=1, color=HexColor('#2874a6')))
    story.append(Spacer(1, 3*mm))
    
    story.append(Paragraph("7.1 下载流程", heading2_style))
    
    download_steps = [
        "从 ServerParamsQueryResponse 或 DispatchTask 获取文件名和下载地址",
        "生成时间戳 timestamp（秒级）",
        "计算签名 sign = md5('crccAuthentication' + timestamp)",
        "构造 HTTP 请求，添加 Header: timestamp、sign、projectid",
        "使用 libcurl 下载文件到本地目录",
        "如果是任务文件（tar.gz），则调用 TarGzExtractor 解压",
        "使用 TrajParser 解析轨迹文件，提取路径点数据"
    ]
    
    for i, step in enumerate(download_steps, 1):
        story.append(Paragraph(f"{i}. {step}", bullet_style))
    
    story.append(Spacer(1, 3*mm))
    story.append(Paragraph("7.2 HTTP 请求头格式", heading2_style))
    
    headers_list = [
        "timestamp: 1717000000",
        "sign: abc123def456...（MD5 签名）",
        "projectid: 从鉴权结果获取"
    ]
    
    for header in headers_list:
        story.append(Paragraph(f"  {header}", code_style))
    
    story.append(PageBreak())
    
    # ========== 8. 数据流全景图 ==========
    story.append(Paragraph("8. 数据流全景图", heading1_style))
    story.append(HRFlowable(width="100%", thickness=1, color=HexColor('#2874a6')))
    story.append(Spacer(1, 3*mm))
    
    story.append(Paragraph("8.1 上行数据流（车端 -> 云端）", heading2_style))
    
    uplink_data = [
        ['数据名称', '发送频率', 'Topic', '消息类型'],
        ['位置报告', '1 秒', 'up/truck/{imei}', 'TruckPositionReport'],
        ['监控报告', '1 秒', 'up/truck/{imei}', 'TruckMonitorReport'],
        ['状态报告', '10 秒', 'up/truck/{imei}', 'TruckSateReport'],
        ['障碍物信息', '事件触发', 'up/truck/{imei}', 'StopObstacleInfo'],
    ]
    
    uplink_table = Table(uplink_data, colWidths=[2.5*cm, 2*cm, 3.5*cm, 5*cm])
    uplink_table.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (-1, -1), 'SimSun' if font_path else 'Helvetica'),
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('BACKGROUND', (0, 0), (-1, 0), HexColor('#2874a6')),
        ('TEXTCOLOR', (0, 0), (-1, 0), white),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('GRID', (0, 0), (-1, -1), 0.5, HexColor('#aed6f1')),
        ('BOX', (0, 0), (-1, -1), 1, HexColor('#2874a6')),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [white, HexColor('#eaf2f8')]),
    ]))
    story.append(uplink_table)
    
    story.append(Spacer(1, 5*mm))
    story.append(Paragraph("8.2 下行数据流（云端 -> 车端）", heading2_style))
    
    downlink_data = [
        ['数据名称', '触发条件', 'Topic', '消息类型'],
        ['鉴权响应', '鉴权请求后', 'down/truck/{imei}', 'AuthenticationApply'],
        ['任务调度', '云端派发', '/retain/down/dispatch/task/...', 'DispatchTask'],
        ['路权信息', '云端下发', 'down/truck/{imei}', 'MovemntAuthoritySend'],
        ['参数查询响应', '查询请求后', 'down/truck/{imei}', 'ServerParamsQueryResponse'],
        ['车辆状态指令', '云端更新', '/retain/down/status/...', 'TruckStatus'],
    ]
    
    downlink_table = Table(downlink_data, colWidths=[2.5*cm, 2.5*cm, 4*cm, 4*cm])
    downlink_table.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (-1, -1), 'SimSun' if font_path else 'Helvetica'),
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('BACKGROUND', (0, 0), (-1, 0), HexColor('#2874a6')),
        ('TEXTCOLOR', (0, 0), (-1, 0), white),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('GRID', (0, 0), (-1, -1), 0.5, HexColor('#aed6f1')),
        ('BOX', (0, 0), (-1, -1), 1, HexColor('#2874a6')),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [white, HexColor('#eaf2f8')]),
    ]))
    story.append(downlink_table)
    
    story.append(PageBreak())
    
    # ========== 9. 关键数据结构 ==========
    story.append(Paragraph("9. 关键数据结构", heading1_style))
    story.append(HRFlowable(width="100%", thickness=1, color=HexColor('#2874a6')))
    story.append(Spacer(1, 3*mm))
    
    story.append(Paragraph("9.1 FileInfo 结构", heading2_style))
    story.append(Paragraph("用于记录文件信息（名称和 MD5）:", body_style))
    
    fileinfo_data = [
        ['字段', '类型', '说明'],
        ['name', 'std::string', '文件名称'],
        ['md5', 'std::string', '文件 MD5 校验值'],
        ['is_ready()', 'bool', '检查文件信息是否完整'],
    ]
    
    fileinfo_table = Table(fileinfo_data, colWidths=[3*cm, 3*cm, 7*cm])
    fileinfo_table.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (-1, -1), 'SimSun' if font_path else 'Helvetica'),
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('BACKGROUND', (0, 0), (-1, 0), HexColor('#2874a6')),
        ('TEXTCOLOR', (0, 0), (-1, 0), white),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('GRID', (0, 0), (-1, -1), 0.5, HexColor('#aed6f1')),
        ('BOX', (0, 0), (-1, -1), 1, HexColor('#2874a6')),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [white, HexColor('#eaf2f8')]),
    ]))
    story.append(fileinfo_table)
    
    story.append(Spacer(1, 5*mm))
    story.append(Paragraph("9.2 TruckPositionReport 字段", heading2_style))
    story.append(Paragraph("位置报告包含的关键字段:", body_style))
    
    position_fields = [
        "longitude/latitude: 经纬度坐标",
        "altitude: 高程",
        "direction: 航向角",
        "speed: 速度",
        "roadId: 车道编号",
        "pointIndex: 当前位置点序号",
        "roadResidualDistance: 当前车道剩余距离",
        "taskSn/taskType/taskStatus: 任务相关信息",
        "commandType/actionType/actionStatus: 动作状态信息"
    ]
    
    for field in position_fields:
        story.append(Paragraph(f"  - {field}", bullet_style))
    
    story.append(PageBreak())
    
    # ========== 10. 错误处理机制 ==========
    story.append(Paragraph("10. 错误处理机制", heading1_style))
    story.append(HRFlowable(width="100%", thickness=1, color=HexColor('#2874a6')))
    story.append(Spacer(1, 3*mm))
    
    story.append(Paragraph("10.1 连接错误处理", heading2_style))
    
    error_handling = [
        "MQTT 连接失败：循环重试，间隔 10 秒",
        "MQTT 断开连接：自动重连机制（paho-mqtt 内置）",
        "鉴权失败：每 5 秒重新发送鉴权消息",
        "文件下载失败：记录错误日志，不重试"
    ]
    
    for error in error_handling:
        story.append(Paragraph(f"  - {error}", bullet_style))
    
    story.append(Spacer(1, 3*mm))
    story.append(Paragraph("10.2 状态检查机制", heading2_style))
    story.append(Paragraph("所有上行数据发送前都调用 checkStatus() 检查:", body_style))
    
    check_items = [
        "mqtt_connect_flag_: MQTT 是否连接成功",
        "authentication_flag_: 是否鉴权成功",
        "init_flag_: 系统初始化是否成功"
    ]
    
    for item in check_items:
        story.append(Paragraph(f"  - {item}", bullet_style))
    
    story.append(Spacer(1, 5*mm))
    story.append(Paragraph("10.3 日志记录", heading2_style))
    story.append(Paragraph("使用自定义日志宏记录关键事件:", body_style))
    
    log_levels = [
        "IINFO: 信息日志（连接成功、鉴权成功、任务下发等）",
        "IWARN: 警告日志（调度失败、下载失败等）",
        "IERROR: 错误日志（下载错误、连接失败等）",
        "IDEBUG: 调试日志（感知数据详情等）"
    ]
    
    for level in log_levels:
        story.append(Paragraph(f"  - {level}", bullet_style))
    
    story.append(PageBreak())
    
    # ========== 总结 ==========
    story.append(Paragraph("总结", heading1_style))
    story.append(HRFlowable(width="100%", thickness=1, color=HexColor('#2874a6')))
    story.append(Spacer(1, 3*mm))
    
    story.append(Paragraph(
        "Gateway 模块作为矿用卡车仿真平台的核心通信网关，实现了完整的双向数据交互能力。",
        body_style
    ))
    story.append(Paragraph("主要特点包括:", body_style))
    
    summary_points = [
        "基于 MQTT 协议的云端通信，支持鉴权、任务调度、路权下发等功能",
        "基于 DDS（FastDDS）的本地进程间通信，实现与感知、规划模块的高效数据交换",
        "支持 HTTP 文件下载，具备 MD5 签名验证机制",
        "采用多线程架构，保证实时性和响应性",
        "完善的错误处理和状态检查机制，提高系统可靠性",
        "模块化设计，易于扩展和维护"
    ]
    
    for point in summary_points:
        story.append(Paragraph(f"  - {point}", bullet_style))
    
    story.append(Spacer(1, 10*mm))
    story.append(Paragraph("--- 文档结束 ---", ParagraphStyle(
        'End', parent=body_style, alignment=TA_CENTER, 
        textColor=HexColor('#7f8c8d'), fontName='SimSun-Bold' if font_path else 'Helvetica-Bold'
    )))
    
    # 构建 PDF
    doc.build(story)
    print(f"PDF 文档已生成: {output_path}")


if __name__ == "__main__":
    output_path = "/home/zy/SIM/Gateway_数据交互逻辑说明文档.pdf"
    create_pdf(output_path)
