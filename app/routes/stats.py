import falcon
import json
from datetime import datetime, timedelta
from collections import defaultdict
from app.models import QueueRecord, Store, FittingRoom, QUEUE_STATUS


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
            if r.call_time and r.queue_time:
                delta = (r.call_time - r.queue_time).total_seconds()
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
                if r.call_time and r.queue_time:
                    delta = (r.call_time - r.queue_time).total_seconds()
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
            if r.call_time and r.queue_time:
                delta = (r.call_time - r.queue_time).total_seconds()
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
