import falcon
import json
from datetime import datetime, timedelta
from collections import defaultdict
from app.models import (
    QueueRecord, Store, FittingRoom, QUEUE_STATUS,
    Appointment, NoShowRecord, ROOM_TYPES, DEFAULT_TIME_SLOTS
)


class StatsOverviewResource:
    async def on_get(self, req, resp):
        days = req.get_param_as_int("days") or 7
        start_date = datetime.now() - timedelta(days=days)

        total_records = await QueueRecord.objects.filter(queue_time__gte=start_date).count()
        entered_records = await QueueRecord.objects.filter(
            queue_time__gte=start_date,
            status__in=["entered", "left"]
        ).count()
        overtime_records = await QueueRecord.objects.filter(
            queue_time__gte=start_date,
            is_overtime=True
        ).count()

        wait_time_records = await QueueRecord.objects.filter(
            queue_time__gte=start_date,
            enter_time__isnull=False
        ).all()

        total_wait_seconds = 0
        valid_count = 0
        for r in wait_time_records:
            if r.enter_time and r.queue_time:
                delta = (r.enter_time - r.queue_time).total_seconds()
                if delta > 0:
                    total_wait_seconds += delta
                    valid_count += 1

        avg_wait_minutes = round(total_wait_seconds / valid_count / 60, 1) if valid_count > 0 else 0
        overtime_rate = round(overtime_records / total_records * 100, 1) if total_records > 0 else 0

        resp.media = {
            "code": 0,
            "message": "获取成功",
            "data": {
                "total_records": total_records,
                "entered_records": entered_records,
                "overtime_records": overtime_records,
                "avg_wait_minutes": avg_wait_minutes,
                "overtime_rate": overtime_rate,
                "days": days
            }
        }


class StatsHourlyResource:
    async def on_get(self, req, resp):
        days = req.get_param_as_int("days") or 7
        store_id = req.get_param_as_int("store_id")
        start_date = datetime.now() - timedelta(days=days)

        query = QueueRecord.objects.filter(queue_time__gte=start_date)
        if store_id is not None:
            query = query.filter(store__id=store_id)

        records = await query.all()

        hourly_data = defaultdict(int)
        hourly_overtime = defaultdict(int)

        for r in records:
            hour = r.queue_time.hour
            hourly_data[hour] += 1
            if r.is_overtime:
                hourly_overtime[hour] += 1

        result = []
        for hour in range(9, 22):
            count = hourly_data.get(hour, 0)
            overtime = hourly_overtime.get(hour, 0)
            result.append({
                "hour": f"{hour:02d}:00",
                "hour_num": hour,
                "count": count,
                "overtime": overtime,
                "overtime_rate": round(overtime / count * 100, 1) if count > 0 else 0
            })

        max_count = max((d["count"] for d in result), default=0)
        for d in result:
            d["heat_level"] = 0
            if max_count > 0:
                ratio = d["count"] / max_count
                if ratio >= 0.8:
                    d["heat_level"] = 4
                elif ratio >= 0.6:
                    d["heat_level"] = 3
                elif ratio >= 0.4:
                    d["heat_level"] = 2
                elif ratio >= 0.2:
                    d["heat_level"] = 1

        peak_hour = max(result, key=lambda x: x["count"]) if result else None

        resp.media = {
            "code": 0,
            "message": "获取成功",
            "data": {
                "hourly_stats": result,
                "peak_hour": peak_hour,
                "days": days
            }
        }


class StatsStoreResource:
    async def on_get(self, req, resp):
        days = req.get_param_as_int("days") or 7
        start_date = datetime.now() - timedelta(days=days)

        stores = await Store.objects.filter(status=True).all()
        result = []

        for store in stores:
            records = await QueueRecord.objects.filter(
                queue_time__gte=start_date,
                store__id=store.id
            ).all()

            total = len(records)
            entered = len([r for r in records if r.status in ["entered", "left"]])
            overtime = len([r for r in records if r.is_overtime])

            wait_times = []
            for r in records:
                if r.enter_time and r.queue_time:
                    delta = (r.enter_time - r.queue_time).total_seconds()
                    if delta > 0:
                        wait_times.append(delta)

            avg_wait = round(sum(wait_times) / len(wait_times) / 60, 1) if wait_times else 0
            overtime_rate = round(overtime / total * 100, 1) if total > 0 else 0

            try:
                rooms_count = await store.fitting_rooms.count()
            except Exception:
                rooms_count = 0

            result.append({
                "store_id": store.id,
                "store_name": store.name,
                "floor": store.floor,
                "rooms_count": rooms_count,
                "total": total,
                "entered": entered,
                "overtime": overtime,
                "avg_wait_minutes": avg_wait,
                "overtime_rate": overtime_rate
            })

        result.sort(key=lambda x: x["total"], reverse=True)
        max_total = max((s["total"] for s in result), default=0)
        for s in result:
            s["heat_level"] = 0
            if max_total > 0:
                ratio = s["total"] / max_total
                if ratio >= 0.8:
                    s["heat_level"] = 4
                elif ratio >= 0.6:
                    s["heat_level"] = 3
                elif ratio >= 0.4:
                    s["heat_level"] = 2
                elif ratio >= 0.2:
                    s["heat_level"] = 1

        resp.media = {
            "code": 0,
            "message": "获取成功",
            "data": result
        }


class StatsDailyResource:
    async def on_get(self, req, resp):
        days = req.get_param_as_int("days") or 30
        start_date = datetime.now() - timedelta(days=days)
        start_date = start_date.replace(hour=0, minute=0, second=0, microsecond=0)

        records = await QueueRecord.objects.filter(queue_time__gte=start_date).all()

        daily_data = defaultdict(lambda: {"total": 0, "entered": 0, "overtime": 0, "wait_times": []})

        for r in records:
            day_key = r.queue_time.strftime("%Y-%m-%d")
            daily_data[day_key]["total"] += 1
            if r.status in ["entered", "left"]:
                daily_data[day_key]["entered"] += 1
            if r.is_overtime:
                daily_data[day_key]["overtime"] += 1
            if r.enter_time and r.queue_time:
                delta = (r.enter_time - r.queue_time).total_seconds()
                if delta > 0:
                    daily_data[day_key]["wait_times"].append(delta)

        result = []
        for i in range(days):
            current_day = (start_date + timedelta(days=i)).strftime("%Y-%m-%d")
            d = daily_data.get(current_day, {"total": 0, "entered": 0, "overtime": 0, "wait_times": []})
            wait_times = d["wait_times"]
            avg_wait = round(sum(wait_times) / len(wait_times) / 60, 1) if wait_times else 0
            overtime_rate = round(d["overtime"] / d["total"] * 100, 1) if d["total"] > 0 else 0

            result.append({
                "date": current_day,
                "total": d["total"],
                "entered": d["entered"],
                "overtime": d["overtime"],
                "avg_wait_minutes": avg_wait,
                "overtime_rate": overtime_rate
            })

        resp.media = {
            "code": 0,
            "message": "获取成功",
            "data": result
        }


class StatsAppointmentResource:
    async def on_get(self, req, resp):
        days = req.get_param_as_int("days") or 7
        store_id = req.get_param_as_int("store_id")
        start_date = datetime.now() - timedelta(days=days)
        start_date_str = start_date.strftime("%Y-%m-%d")

        apt_query = Appointment.objects.filter(created_at__gte=start_date)
        if store_id is not None:
            apt_query = apt_query.filter(store__id=store_id)

        appointments = await apt_query.all()

        total_appointments = len(appointments)
        confirmed = len([a for a in appointments if a.status == "confirmed"])
        cancelled = len([a for a in appointments if a.status == "cancelled"])
        no_show = len([a for a in appointments if a.status == "no_show"])
        expired = len([a for a in appointments if a.status == "expired"])
        pending = len([a for a in appointments if a.status == "pending"])

        arrival_rate = round(confirmed / total_appointments * 100, 1) if total_appointments > 0 else 0
        no_show_rate = round(no_show / total_appointments * 100, 1) if total_appointments > 0 else 0
        cancel_rate = round(cancelled / total_appointments * 100, 1) if total_appointments > 0 else 0

        queue_appointments = len([a for a in appointments if a.status == "confirmed"])
        onsite_total = 0
        if days > 0:
            queue_query = QueueRecord.objects.filter(
                queue_time__gte=start_date,
                source="on_site"
            )
            if store_id is not None:
                queue_query = queue_query.filter(store__id=store_id)
            onsite_total = await queue_query.count()

        total_queue = queue_appointments + onsite_total
        appointment_ratio = round(queue_appointments / total_queue * 100, 1) if total_queue > 0 else 0

        no_show_query = NoShowRecord.objects.filter(recorded_at__gte=start_date)
        if store_id is not None:
            no_show_query = no_show_query.filter(store__id=store_id)
        no_show_records = await no_show_query.all()

        repeat_offenders = defaultdict(int)
        for ns in no_show_records:
            repeat_offenders[ns.phone] += 1
        blocked_users = len([p for p, c in repeat_offenders.items() if c >= 3])

        room_type_stats = defaultdict(lambda: {"total": 0, "confirmed": 0, "no_show": 0})
        for a in appointments:
            rt = a.room_type
            room_type_stats[rt]["total"] += 1
            if a.status == "confirmed":
                room_type_stats[rt]["confirmed"] += 1
            if a.status == "no_show":
                room_type_stats[rt]["no_show"] += 1

        room_type_result = []
        for rt, stats in room_type_stats.items():
            total = stats["total"]
            room_type_result.append({
                "room_type": rt,
                "room_type_text": ROOM_TYPES.get(rt, rt),
                "total": total,
                "confirmed": stats["confirmed"],
                "no_show": stats["no_show"],
                "arrival_rate": round(stats["confirmed"] / total * 100, 1) if total > 0 else 0,
                "no_show_rate": round(stats["no_show"] / total * 100, 1) if total > 0 else 0
            })

        daily_data = defaultdict(lambda: {
            "total": 0, "confirmed": 0, "cancelled": 0, "no_show": 0
        })
        for a in appointments:
            day_key = a.appointment_date
            daily_data[day_key]["total"] += 1
            if a.status == "confirmed":
                daily_data[day_key]["confirmed"] += 1
            elif a.status == "cancelled":
                daily_data[day_key]["cancelled"] += 1
            elif a.status == "no_show":
                daily_data[day_key]["no_show"] += 1

        daily_result = []
        for i in range(days):
            current_day = (start_date + timedelta(days=i)).strftime("%Y-%m-%d")
            d = daily_data.get(current_day, {"total": 0, "confirmed": 0, "cancelled": 0, "no_show": 0})
            total = d["total"]
            daily_result.append({
                "date": current_day,
                "total": total,
                "confirmed": d["confirmed"],
                "cancelled": d["cancelled"],
                "no_show": d["no_show"],
                "arrival_rate": round(d["confirmed"] / total * 100, 1) if total > 0 else 0,
                "no_show_rate": round(d["no_show"] / total * 100, 1) if total > 0 else 0
            })

        resp.media = {
            "code": 0,
            "message": "获取成功",
            "data": {
                "days": days,
                "summary": {
                    "total_appointments": total_appointments,
                    "confirmed": confirmed,
                    "cancelled": cancelled,
                    "no_show": no_show,
                    "expired": expired,
                    "pending": pending,
                    "arrival_rate": arrival_rate,
                    "no_show_rate": no_show_rate,
                    "cancel_rate": cancel_rate,
                    "appointment_queue_ratio": appointment_ratio,
                    "onsite_queue_count": onsite_total,
                    "appointment_queue_count": queue_appointments,
                    "blocked_users_count": blocked_users,
                    "repeat_offenders_count": len(repeat_offenders)
                },
                "room_type_stats": room_type_result,
                "daily_stats": daily_result
            }
        }


class StatsAppointmentPeakResource:
    async def on_get(self, req, resp):
        days = req.get_param_as_int("days") or 7
        store_id = req.get_param_as_int("store_id")
        start_date = datetime.now() - timedelta(days=days)
        start_date_str = start_date.strftime("%Y-%m-%d")

        apt_query = Appointment.objects.filter(
            created_at__gte=start_date,
            status__in=["confirmed", "pending"]
        )
        if store_id is not None:
            apt_query = apt_query.filter(store__id=store_id)

        appointments = await apt_query.all()

        slot_data = defaultdict(lambda: {"total": 0, "confirmed": 0})
        hour_data = defaultdict(lambda: {"total": 0, "confirmed": 0})
        weekday_data = defaultdict(lambda: {"total": 0, "confirmed": 0})

        weekday_map = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]

        for a in appointments:
            slot = a.time_slot
            slot_data[slot]["total"] += 1
            if a.status == "confirmed":
                slot_data[slot]["confirmed"] += 1

            try:
                hour_start = int(slot.split("-")[0].split(":")[0])
                hour_data[hour_start]["total"] += 1
                if a.status == "confirmed":
                    hour_data[hour_start]["confirmed"] += 1
            except Exception:
                pass

            try:
                apt_date = datetime.strptime(a.appointment_date, "%Y-%m-%d")
                weekday_idx = apt_date.weekday()
                weekday_data[weekday_idx]["total"] += 1
                if a.status == "confirmed":
                    weekday_data[weekday_idx]["confirmed"] += 1
            except Exception:
                pass

        slot_result = []
        for slot in DEFAULT_TIME_SLOTS:
            d = slot_data.get(slot, {"total": 0, "confirmed": 0})
            total = d["total"]
            slot_result.append({
                "time_slot": slot,
                "total": total,
                "confirmed": d["confirmed"],
                "utilization": round(d["confirmed"] / max(1, 5 * days) * 100, 1)
            })

        max_slot_total = max((s["total"] for s in slot_result), default=0)
        for s in slot_result:
            s["heat_level"] = 0
            if max_slot_total > 0:
                ratio = s["total"] / max_slot_total
                if ratio >= 0.8:
                    s["heat_level"] = 4
                elif ratio >= 0.6:
                    s["heat_level"] = 3
                elif ratio >= 0.4:
                    s["heat_level"] = 2
                elif ratio >= 0.2:
                    s["heat_level"] = 1

        hour_result = []
        for hour in range(9, 22):
            d = hour_data.get(hour, {"total": 0, "confirmed": 0})
            total = d["total"]
            hour_result.append({
                "hour": f"{hour:02d}:00",
                "hour_num": hour,
                "total": total,
                "confirmed": d["confirmed"],
                "arrival_rate": round(d["confirmed"] / total * 100, 1) if total > 0 else 0
            })

        max_hour_total = max((h["total"] for h in hour_result), default=0)
        for h in hour_result:
            h["heat_level"] = 0
            if max_hour_total > 0:
                ratio = h["total"] / max_hour_total
                if ratio >= 0.8:
                    h["heat_level"] = 4
                elif ratio >= 0.6:
                    h["heat_level"] = 3
                elif ratio >= 0.4:
                    h["heat_level"] = 2
                elif ratio >= 0.2:
                    h["heat_level"] = 1

        weekday_result = []
        for i in range(7):
            d = weekday_data.get(i, {"total": 0, "confirmed": 0})
            total = d["total"]
            weekday_result.append({
                "weekday": weekday_map[i],
                "weekday_idx": i,
                "total": total,
                "confirmed": d["confirmed"],
                "arrival_rate": round(d["confirmed"] / total * 100, 1) if total > 0 else 0
            })

        max_weekday_total = max((w["total"] for w in weekday_result), default=0)
        for w in weekday_result:
            w["heat_level"] = 0
            if max_weekday_total > 0:
                ratio = w["total"] / max_weekday_total
                if ratio >= 0.8:
                    w["heat_level"] = 4
                elif ratio >= 0.6:
                    w["heat_level"] = 3
                elif ratio >= 0.4:
                    w["heat_level"] = 2
                elif ratio >= 0.2:
                    w["heat_level"] = 1

        peak_slot = max(slot_result, key=lambda x: x["total"]) if slot_result else None
        peak_hour = max(hour_result, key=lambda x: x["total"]) if hour_result else None
        peak_weekday = max(weekday_result, key=lambda x: x["total"]) if weekday_result else None

        resp.media = {
            "code": 0,
            "message": "获取成功",
            "data": {
                "days": days,
                "slot_stats": slot_result,
                "hour_stats": hour_result,
                "weekday_stats": weekday_result,
                "peaks": {
                    "peak_slot": peak_slot,
                    "peak_hour": peak_hour,
                    "peak_weekday": peak_weekday
                }
            }
        }
