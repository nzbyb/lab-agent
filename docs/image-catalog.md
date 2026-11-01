# 实验室与设备图片目录

2026-11-01：8 个实验室、32 台/项设备，共 36 张图片。同类型重复设备共用对应图片。

图片用于类型和外观展示：实验室图片并非本校实拍；部分设备仅匹配类别，不能据此认定为数据库所列配置。UR5 为 RoboDK 模型示意图。图片版权归原来源所有；未核实为开放许可，公开发布前应确认相应使用授权。

原图已转换为本地 JPEG；设备保持比例并留白，实验室封面为 1200×750。数据库只存 `/uploads/catalog-20261101/...jpg` 地址。完整来源、校验值及逐条数据库映射见 `backend/assets/image-catalog/manifest.json`。

**这 36 张 jpg 不进仓库**（见 `.gitignore`）：版权未核实，而仓库是公开的、挂 MIT 许可，推上去等于公开分发。仓库里只保留 `manifest.json`（文件名、校验值、来源链接）和下面这个脚本。部署到新环境时，从本机把 `backend/assets/image-catalog/*.jpg` 单独拷进容器再跑脚本，见「更新和恢复」。

## 更新和恢复

脚本默认只预览。它校验 ID、名称、设备规格和所属实验室；只写 `img`，并在同一事务中检查其余字段没有变化。每次实际写入前生成备份，恢复时校验当前值，防止覆盖后来手动更换的图片。不会执行 `demo_data.sql` 或清空数据。

本机（项目根目录）：

```powershell
& backend/.venv/Scripts/python.exe -B backend/scripts/apply_image_catalog.py
& backend/.venv/Scripts/python.exe -B backend/scripts/apply_image_catalog.py --apply --backup-dir backups/image-catalog
```

Docker（图片和脚本都要先放进容器，仓库里没有 jpg）：

```powershell
# 1. 把本地图片拷进容器（容器里已有 manifest.json 和脚本）
docker cp backend/assets/image-catalog/. lab-agent-backend-1:/app/assets/image-catalog/
# 2. 先预览，再写入
docker compose exec -T backend python scripts/apply_image_catalog.py
docker compose exec -T backend python scripts/apply_image_catalog.py --apply --backup-dir /tmp/image-catalog-backups
# 3. 把备份复制到宿主机 backups/image-catalog 后妥善保管
```

注意 `docker cp` 进容器的东西在**重建容器**后会消失，但脚本已经把图片复制进 `uploads` 持久卷、
数据库里也写好了地址，所以只是"以后想重跑脚本时要再拷一次"，不影响网站显示。

恢复（使用对应数据库环境与其备份文件；默认仍是预览）。如同一记录更新过多次，按备份时间从新到旧逐次恢复：

```powershell
& backend/.venv/Scripts/python.exe -B backend/scripts/apply_image_catalog.py --rollback backups/image-catalog/<backup>.json --apply --backup-dir backups/image-catalog
```

源图位于本机 `backend/assets/image-catalog`，**不进仓库**（版权未核实）。脚本把校验后的图片复制到 uploads 目录后再提交图片地址；Docker 中 uploads 为持久卷，不需要重启应用或电脑。以后重新初始化演示数据时，再运行本脚本即可补充图片。

## 图片来源

| 用途 | 图片标题 | 来源页面 |
| --- | --- | --- |
| 计算机实验室 | Computer Lab / KLE BBA | [原始来源](https://klecbalc.edu.in/computer-lab/) |
| 电子实验室 | IIT Bombay Electrical Engineering electrical equipment scene | [原始来源](https://www.ee.iitb.ac.in/) |
| 物理实验室 | 大学物理实验室-智能工程学部-新乡工程学院 | [原始来源](https://www.xxgc.edu.cn/ee/info/1054/1577.htm) |
| 化学实验室 | 化学实验室-北京微纳光科自动化设备有限公司 | [原始来源](https://www.bjwn.cn/ShowNews.asp?ArticleID=2404&id=1) |
| 生物实验室 | 浙江大学生物学国家级实验教学示范中心 | [原始来源](https://zjubiolab.zju.edu.cn/page/labchannel/tslab/detail/78/2027) |
| 人工智能实验室 | Computer research / teaching room | [原始来源](https://ayinfotechgh.com/computer-labs-in-schools/) |
| 机器人实验室 | 机器人智能制造实验室-烟台理工学院人工智能学院 | [原始来源](https://ai.yitsd.edu.cn/info/1027/1239.htm) |
| 软件工程实验室 | Computer teaching lab | [原始来源](https://blog.rentacomputer.com/2019/09/06/building-the-perfect-computer-lab-rentals-let-you-test-before-you-buy/) |
| RTX4090、深度学习训练显卡 | NVIDIA GeForce RTX 4090 | [原始来源](https://www.nvidia.com/en-us/geforce/graphics-cards/40-series/rtx-4090/) |
| 开发主机 | Lenovo desktop host | [原始来源](https://www.xybhshop.com/) |
| 投影仪 | Epson LCD projector | [原始来源](https://post.smzdm.com/p/ad9m2m7x/) |
| 千兆交换机 | TP-Link TL-SG1024 24-port Gigabit switch | [原始来源](https://www.tp-link.com/us/business-networking/unmanaged-switch/tl-sg1024/) |
| 示波器 | HD304MSO InfiniiVision HD3系列示波器-KEYSIGHT HD304MSO-数字示波器-东方中科 | [原始来源](https://www.dfzk.com/prod_keysight_hd304mso.html) |
| 信号发生器 | Siglent SDG1062X 60MHz | [原始来源](https://siglentna.com/waveform-generators/sdg1000x-series-functionarbitrary-waveform-generators/) |
| 数字万用表 | UT890D+数字万用表--罗伯克测控--苏州罗伯克测控技术有限公司 | [原始来源](http://www.rbt-sz.com/product_show.php?product_id=91) |
| 直流稳压电源 | Siglent SPD3303X bench supply | [原始来源](https://siglentna.com/power-supplies/spd3303x-spd3303x-e-series-programmable-dc-power-supply/) |
| 光学实验台 | 广州基座光学科技有限公司_OP系列 光学隔振平台 | [原始来源](https://www.oeabt.com/show.php?id=85) |
| 氦氖激光器 | Newport N-LHP-151 HeNe laser 632.8nm | [原始来源](https://www.newport.com.cn/p/N-LHP-151) |
| 力学轨道 | PASCO air track | [原始来源](https://www.pasco.com/products/lab-apparatus/mechanics/air-tracks/sf-9214) |
| 分光计 | 分光计 - 上海茅林光电科技有限公司 | [原始来源](http://www.morningoptical.com/h-pd-2550.html) |
| 电子天平 | Exploring the Different Types of Laboratory Analytical Balances - Drawell | [原始来源](https://www.drawellanalytical.com/exploring-the-different-types-of-laboratory-analytical-balances/) |
| 离心机 | 台式离心机4000/4200_广州守诚贸易发展有限公司 | [原始来源](http://www.olybota.cn/index.php?m=home&c=View&a=index&aid=99) |
| 通风橱 | Laboratory fume hood | [原始来源](http://www.gz-jmh.cn/products.php?act=detail&id=207) |
| pH 计 | PH计,酸度计_上海三信 | [原始来源](http://www.shsanxin.com.cn/PH/) |
| 显微镜 | Optical compound microscope | [原始来源](https://www.viyeechina.com/dynamic/1523.html) |
| 恒温培养箱 | Biostream BH-1200恒温培养箱 - Biostream振荡培养箱 - Biostream-上海博奥思生物技术有限公司 | [原始来源](https://cn.biostream.com/show-175-689-1.html) |
| 移液器 | Micropipette – LabCore Scientific | [原始来源](https://labcorescientific.com/product/micropipette/) |
| PCR 仪 | TIANGEN TGreat Expert thermal cycler | [原始来源](https://www.tiangen.com/content/details_101_22687.html) |
| GPU 训练服务器 | NVIDIA GPU rack systems | [原始来源](https://www.nvidia.com/en-us/data-center/dgx-platform/) |
| 深度相机、RealSense 深度相机 | RealSense D435i | [原始来源](https://store.realsenseai.com/buy-realsense-depth-camera-d435i.html) |
| 标注工作站 | Lenovo ThinkStation P410 | [原始来源](https://www.bjzfkt.com/Mobile/Products/gongzuozhanP410.html) |
| UR5 机械臂 | Universal Robots UR5 model illustration (RoboDK) | [原始来源](https://robodk.com/robot/Universal-Robots/UR5) |
| Livox 激光雷达 | Livox Mid-360 | [原始来源](https://www.livoxtech.com/mid-360) |
| Jetson Orin | NVIDIA Jetson AGX Orin Developer Kit | [原始来源](https://www.nvidia.com/en-us/autonomous-machines/embedded-systems/jetson-orin/) |
| 显示器 | 戴尔显示器-DELL显示器-戴尔DELL企业官网 | [原始来源](https://www.dellemc-solution.com/product/monitor.html?category=equipment&gacd=9788180-2216869-0-7paWM-0&dgc=mb&cid=2216869&lid=7paWM) |
| 代码服务器 | ZTE rack server | [原始来源](https://sdnfv.zte.com.cn/zh-CN/products/ICT-hardware/server) |
