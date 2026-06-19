# 商场试衣间排队叫号与遗留物封存处理系统

基于 Python + Falcon + Ormar + MySQL + Alpine.js + Tailwind CSS 构建的商场试衣间智能管理系统。

## 功能特性

### 核心模块
- **用户登录认证**：基于 JWT 的身份验证，支持管理员和员工角色
- **楼层门店管理**：多楼层、多门店的增删改查管理
- **试衣间管理**：试衣间编号、类型、状态管理，支持清场标记
- **排队叫号系统**：
  - 现场取号（手机号唯一约束）
  - 叫号入场
  - 入场登记
  - 离场登记
  - 超时过号处理
  - 过号重排（自动排到队尾）
- **遗留物管理**：
  - 遗留物登记
  - 物品封存（关联试衣间封存）
  - 失物认领登记
  - 认领约束（不可二次认领）
- **数据统计分析**：
  - 平均等候时长
  - 过号率统计
  - 时段热度分析
  - 门店热度排行
  - 每日趋势报表

### 业务约束实现
1. ✅ 同一手机号在未完成当前排队前不能重复取号
2. ✅ 离场前不能登记下一位顾客入场（试衣间状态流转控制）
3. ✅ 遗留物封存后原试衣间必须完成清场才能恢复使用
4. ✅ 过号记录不能恢复到原始队头位置（只能重排到队尾）
5. ✅ 认领成功后不能重复发起二次认领

## 技术架构

```
项目根目录
├── app/                      # 应用主目录
│   ├── models/               # 数据模型
│   │   ├── user.py           # 用户模型
│   │   ├── store.py          # 门店模型
│   │   ├── fitting_room.py   # 试衣间模型
│   │   ├── queue_record.py   # 排队记录模型
│   │   └── lost_item.py      # 遗留物模型
│   ├── routes/               # API路由 + 页面路由
│   ├── middleware/           # 中间件（认证、CORS）
│   ├── templates/            # Jinja2 HTML模板
│   └── config.py             # 应用配置
├── app.py                    # 应用入口 (ASGI)
├── init_db.py                # 数据库初始化脚本
├── requirements.txt          # Python依赖
├── start.bat                 # Windows启动脚本
├── start.sh                  # Linux/Mac启动脚本
└── .env.example              # 环境变量示例
```

## 数据库模型

### 用户表 (users)
| 字段 | 类型 | 说明 |
|------|------|------|
| id | Integer | 主键 |
| username | String(50) | 用户名，唯一 |
| password_hash | String(255) | 密码哈希 (bcrypt) |
| real_name | String(50) | 真实姓名 |
| role | String(20) | 角色：admin/staff |

### 门店表 (stores)
| 字段 | 类型 | 说明 |
|------|------|------|
| id | Integer | 主键 |
| name | String(100) | 门店名称 |
| floor | Integer | 楼层 |
| location | String(200) | 位置 |
| status | Boolean | 营业状态 |

### 试衣间表 (fitting_rooms)
| 字段 | 类型 | 说明 |
|------|------|------|
| id | Integer | 主键 |
| room_number | String(20) | 房间编号，唯一 |
| store_id | Integer | 所属门店（可选） |
| room_type | String(20) | 类型：standard/large/family/vip |
| status | String(20) | 状态：available/occupied/cleaning/sealed |
| last_clean_time | DateTime | 最近清场时间 |

### 排队记录表 (queue_records)
| 字段 | 类型 | 说明 |
|------|------|------|
| id | Integer | 主键 |
| ticket_number | String(20) | 取号编号 |
| store_id | Integer | 门店ID |
| fitting_room_id | Integer | 试衣间ID |
| customer_name | String(50) | 顾客姓名 |
| phone | String(20) | 手机号 |
| queue_time | DateTime | 取号时间 |
| call_time | DateTime | 叫号时间 |
| enter_time | DateTime | 入场时间 |
| leave_time | DateTime | 离场时间 |
| status | String(20) | 状态：waiting/called/entered/left/overtime/abnormal |
| is_overtime | Boolean | 是否过号 |

### 遗留物表 (lost_items)
| 字段 | 类型 | 说明 |
|------|------|------|
| id | Integer | 主键 |
| item_name | String(100) | 物品名称 |
| item_description | Text | 物品描述 |
| fitting_room_id | Integer | 关联试衣间 |
| queue_record_id | Integer | 关联排队记录 |
| status | String(20) | 状态：registered/sealed/claimed/disposed |
| seal_location | String(200) | 封存位置 |
| seal_time | DateTime | 封存时间 |
| claimant_name/phone/id_number | String | 认领人信息 |
| claim_time | DateTime | 认领时间 |

## 快速开始

### 环境要求
- Python 3.8+
- MySQL 5.7+ 或 MariaDB 10.3+

### 安装步骤

1. **克隆或解压项目**
   ```bash
   cd cj91
   ```

2. **配置数据库**
   - 创建 MySQL 数据库：
     ```sql
     CREATE DATABASE fitting_room_queue CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
     ```

3. **配置环境变量**
   ```bash
   # Windows
   copy .env.example .env
   
   # Linux/Mac
   cp .env.example .env
   ```
   编辑 `.env` 文件，修改数据库连接信息：
   ```
   DATABASE_URL=mysql+pymysql://用户名:密码@localhost:3306/fitting_room_queue
   JWT_SECRET_KEY=请修改为随机字符串
   ```

4. **安装依赖**
   ```bash
   pip install -r requirements.txt
   ```

5. **初始化数据库**
   ```bash
   python init_db.py
   ```
   该脚本会自动创建表结构，并初始化：
   - 管理员账号：`admin / admin123`
   - 员工账号：`staff / staff123`
   - 5个示例门店 + 13个试衣间

6. **启动服务**
   ```bash
   # Windows 一键启动
   start.bat
   
   # Linux/Mac 一键启动
   chmod +x start.sh
   ./start.sh
   
   # 或手动启动
   python app.py
   ```

7. **访问系统**
   - 打开浏览器访问：http://localhost:8000
   - 使用默认账号登录：`admin / admin123`

## API 接口文档

### 认证接口
| 方法 | 路径 | 说明 |
|------|------|------|
| POST | /api/login | 登录获取Token |
| GET | /api/user/info | 获取当前用户信息 |

### 门店管理
| 方法 | 路径 | 说明 |
|------|------|------|
| GET | /api/stores | 门店列表 |
| POST | /api/stores | 新增门店 |
| GET | /api/stores/{id} | 门店详情 |
| PUT | /api/stores/{id} | 更新门店 |
| DELETE | /api/stores/{id} | 删除门店 |
| GET | /api/floors | 获取楼层列表 |

### 试衣间管理
| 方法 | 路径 | 说明 |
|------|------|------|
| GET | /api/fitting-rooms | 试衣间列表 |
| POST | /api/fitting-rooms | 新增试衣间 |
| GET | /api/fitting-rooms/{id} | 试衣间详情 |
| PUT | /api/fitting-rooms/{id} | 更新试衣间 |
| DELETE | /api/fitting-rooms/{id} | 删除试衣间 |
| POST | /api/fitting-rooms/{id}/clean | 标记清场完成 |
| GET | /api/fitting-rooms/options | 获取状态和类型选项 |

### 排队叫号
| 方法 | 路径 | 说明 |
|------|------|------|
| GET | /api/queue | 排队记录列表 |
| POST | /api/queue | 现场取号 |
| GET | /api/queue/waiting | 待叫号概览 |
| POST | /api/queue/{id}/call | 叫号 |
| POST | /api/queue/{id}/enter | 入场登记 |
| POST | /api/queue/{id}/leave | 离场登记 |
| POST | /api/queue/{id}/overtime | 标记过号 |
| POST | /api/queue/{id}/requeue | 过号重排（队尾） |

### 遗留物管理
| 方法 | 路径 | 说明 |
|------|------|------|
| GET | /api/lost-items | 遗留物列表 |
| POST | /api/lost-items | 登记遗留物 |
| POST | /api/lost-items/{id}/seal | 物品封存 |
| POST | /api/lost-items/{id}/claim | 失物认领 |
| POST | /api/lost-items/{id}/dispose | 标记处理（无主） |

### 统计分析
| 方法 | 路径 | 说明 |
|------|------|------|
| GET | /api/stats/overview | 总体概览（平均等候、过号率） |
| GET | /api/stats/hourly | 时段热度分析 |
| GET | /api/stats/stores | 门店热度排行 |
| GET | /api/stats/daily | 每日趋势 |

## 页面路由

| 路径 | 功能 |
|------|------|
| /login | 登录页 |
| / | 工作台/仪表盘 |
| /queue | 排队叫号主操作页 |
| /stores | 门店管理 |
| /fitting-rooms | 试衣间管理 |
| /lost-items | 遗留物管理 |
| /stats | 数据统计分析 |

## 常见问题

### 1. 数据库连接失败
- 检查 MySQL 服务是否启动
- 确认 `.env` 中的账号密码正确
- 确认数据库 `fitting_room_queue` 已创建

### 2. 提示 "找不到接受实际参数" 的错误
- 请使用 Windows PowerShell 执行命令，不要使用 CMD
- 或直接执行 `python app.py`

### 3. 如何修改默认端口
- 编辑 `.env` 文件，修改 `APP_PORT` 的值
- 或修改 `app/config.py` 中的默认值

### 4. 忘记管理员密码
- 重新运行 `python init_db.py` 不会覆盖已有账号
- 可手动执行 SQL：
  ```sql
  -- 或直接删除用户后重新初始化
  DELETE FROM users WHERE username = 'admin';
  ```
  然后重新运行 `python init_db.py`

## 开发说明

- 前端采用 Alpine.js 响应式框架 + Tailwind CSS 样式，无需构建
- 所有静态资源（Tailwind、Alpine.js）通过 CDN 加载
- API 接口遵循 RESTful 风格
- 所有业务约束在后端 API 层实现，前端仅作为友好提示

## License

MIT
