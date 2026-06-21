from datetime import datetime, timedelta
from collections import defaultdict

from app.services.base import BaseService
from app.models import (
    QueueRecord, Store, FittingRoom, QUEUE_STATUS,
    Appointment, NoShowRecord, ROOM_TYPES, DEFAULT_TIME_SLOTS,
    StoreTransfer, TRANSFER_STATUS, TRANSFER_REASON, TRANSFER_SOURCE_TYPE,
    classify_load_level, LOAD_LEVEL_TEXT, calc_floor_distance
)


class StatsService(BaseService):

    async def get_overview(self, days: int = 7) -> dict:
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

        return {
            "total_records": total_records,
            "entered_records": entered_records,
            "overtime_records": overtime_records,
            "avg_wait_minutes": avg_wait_minutes,
            "overtime_rate": overtime_rate,
            "days": days
        }

    async def get_hourly_stats(self, days: int = 7, store_id: int = None) -> dict:
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

        return {
            "hourly_stats": result,
            "peak_hour": peak_hour,
            "days": days
        }

    async def get_store_stats(self, days: int = 7) -> list:
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

        return result

    async def get_daily_stats(self, days: int = 30) -> list:
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

        return result

    async def get_appointment_stats(self, days: int = 7, store_id: int = None) -> dict:
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

        return {
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

    async def get_appointment_peak_stats(self, days: int = 7, store_id: int = None) -> dict:
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

        return {
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

    async def get_transfer_overview(self, days: int = 7, store_id: int = None) -> dict:
        start_date = datetime.now() - timedelta(days=days)

        transfer_query = StoreTransfer.objects.filter(created_at__gte=start_date)
        if store_id is not None:
            transfer_query = transfer_query.filter(
                (StoreTransfer.source_store.id == store_id) |
                (StoreTransfer.target_store.id == store_id)
            )
        transfers = await transfer_query.select_related(
            "source_store", "target_store"
        ).all()

        total_transfers = len(transfers)
        completed = len([t for t in transfers if t.status == "completed"])
        customer_rejected = len([t for t in transfers if t.status == "customer_rejected"])
        target_rejected = len([t for t in transfers if t.status == "target_rejected"])
        cancelled = len([t for t in transfers if t.status == "cancelled"])
        pending = len([t for t in transfers if t.status in [
            "pending", "customer_confirmed", "target_accepted"
        ]])
        failed = customer_rejected + target_rejected + cancelled

        success_rate = round(completed / total_transfers * 100, 1) if total_transfers > 0 else 0
        failure_rate = round(failed / total_transfers * 100, 1) if total_transfers > 0 else 0
        customer_confirm_rate = round(
            (total_transfers - customer_rejected) / total_transfers * 100, 1
        ) if total_transfers > 0 else 0

        queue_total = await QueueRecord.objects.filter(
            queue_time__gte=start_date
        ).count()
        if store_id is not None:
            queue_total = await QueueRecord.objects.filter(
                queue_time__gte=start_date,
                store__id=store_id
            ).count()

        outgoing = len([t for t in transfers if t.source_store and t.source_store.id == store_id]) if store_id else len(transfers)
        transfer_rate = round(outgoing / queue_total * 100, 2) if queue_total > 0 else 0

        source_out = defaultdict(int)
        target_in = defaultdict(int)
        for t in transfers:
            if t.source_store:
                source_out[t.source_store.name] += 1
            if t.target_store:
                target_in[t.target_store.name] += 1

        reason_stats = defaultdict(int)
        for t in transfers:
            reason_stats[t.transfer_reason] += 1

        reason_result = []
        for reason, count in sorted(reason_stats.items(), key=lambda x: -x[1]):
            reason_result.append({
                "reason": reason,
                "reason_text": TRANSFER_REASON.get(reason, reason),
                "count": count,
                "percentage": round(count / total_transfers * 100, 1) if total_transfers > 0 else 0
            })

        source_type_stats = defaultdict(lambda: {"total": 0, "completed": 0})
        for t in transfers:
            st = t.source_type
            source_type_stats[st]["total"] += 1
            if t.status == "completed":
                source_type_stats[st]["completed"] += 1

        source_type_result = []
        for st, stats_data in source_type_stats.items():
            total = stats_data["total"]
            source_type_result.append({
                "source_type": st,
                "source_type_text": TRANSFER_SOURCE_TYPE.get(st, st),
                "total": total,
                "completed": stats_data["completed"],
                "success_rate": round(stats_data["completed"] / total * 100, 1) if total > 0 else 0
            })

        avg_floor_dist = 0
        dist_counts = [t.floor_distance for t in transfers if t.floor_distance > 0]
        if dist_counts:
            avg_floor_dist = round(sum(dist_counts) / len(dist_counts), 1)

        return {
            "days": days,
            "overview": {
                "total_transfers": total_transfers,
                "completed": completed,
                "pending": pending,
                "customer_rejected": customer_rejected,
                "target_rejected": target_rejected,
                "cancelled": cancelled,
                "failed": failed,
                "success_rate": success_rate,
                "failure_rate": failure_rate,
                "customer_confirm_rate": customer_confirm_rate,
                "transfer_rate": transfer_rate,
                "avg_floor_distance": avg_floor_dist,
                "related_queue_count": queue_total
            },
            "source_store_ranking": sorted(
                [{"store_name": k, "outgoing_count": v} for k, v in source_out.items()],
                key=lambda x: -x["outgoing_count"]
            ),
            "target_store_ranking": sorted(
                [{"store_name": k, "incoming_count": v} for k, v in target_in.items()],
                key=lambda x: -x["incoming_count"]
            ),
            "reason_stats": reason_result,
            "source_type_stats": source_type_result,
        }

    async def get_transfer_daily(self, days: int = 30, store_id: int = None) -> list:
        start_date = datetime.now() - timedelta(days=days)
        start_date = start_date.replace(hour=0, minute=0, second=0, microsecond=0)

        transfer_query = StoreTransfer.objects.filter(created_at__gte=start_date)
        if store_id is not None:
            transfer_query = transfer_query.filter(
                (StoreTransfer.source_store.id == store_id) |
                (StoreTransfer.target_store.id == store_id)
            )
        transfers = await transfer_query.all()

        daily_data = defaultdict(lambda: {
            "total": 0, "completed": 0, "outgoing": 0, "incoming": 0,
            "customer_rejected": 0, "target_rejected": 0, "cancelled": 0,
            "queue_count": 0
        })

        for t in transfers:
            day_key = t.created_at.strftime("%Y-%m-%d")
            daily_data[day_key]["total"] += 1
            if t.status == "completed":
                daily_data[day_key]["completed"] += 1
            if store_id is not None:
                if t.source_store and t.source_store.id == store_id:
                    daily_data[day_key]["outgoing"] += 1
                if t.target_store and t.target_store.id == store_id:
                    daily_data[day_key]["incoming"] += 1
            else:
                daily_data[day_key]["outgoing"] += 1
            if t.status == "customer_rejected":
                daily_data[day_key]["customer_rejected"] += 1
            if t.status == "target_rejected":
                daily_data[day_key]["target_rejected"] += 1
            if t.status == "cancelled":
                daily_data[day_key]["cancelled"] += 1

        queue_query = QueueRecord.objects.filter(queue_time__gte=start_date)
        if store_id is not None:
            queue_query = queue_query.filter(store__id=store_id)
        queue_records = await queue_query.all()
        for qr in queue_records:
            day_key = qr.queue_time.strftime("%Y-%m-%d")
            daily_data[day_key]["queue_count"] += 1

        result = []
        for i in range(days):
            current_day = (start_date + timedelta(days=i)).strftime("%Y-%m-%d")
            d = daily_data.get(current_day, {
                "total": 0, "completed": 0, "outgoing": 0, "incoming": 0,
                "customer_rejected": 0, "target_rejected": 0, "cancelled": 0,
                "queue_count": 0
            })
            total = d["total"]
            queue_count = d["queue_count"]
            result.append({
                "date": current_day,
                "total": total,
                "completed": d["completed"],
                "outgoing": d["outgoing"],
                "incoming": d["incoming"],
                "customer_rejected": d["customer_rejected"],
                "target_rejected": d["target_rejected"],
                "cancelled": d["cancelled"],
                "success_rate": round(d["completed"] / total * 100, 1) if total > 0 else 0,
                "transfer_rate": round(d["outgoing"] / queue_count * 100, 2) if queue_count > 0 else 0,
                "queue_count": queue_count
            })

        return result

    async def get_transfer_peak_hour(self, days: int = 7, store_id: int = None) -> dict:
        start_date = datetime.now() - timedelta(days=days)

        transfer_query = StoreTransfer.objects.filter(created_at__gte=start_date)
        if store_id is not None:
            transfer_query = transfer_query.filter(
                (StoreTransfer.source_store.id == store_id) |
                (StoreTransfer.target_store.id == store_id)
            )
        transfers = await transfer_query.all()

        hour_data = defaultdict(lambda: {
            "total": 0, "completed": 0, "outgoing": 0, "incoming": 0,
            "busy_reason": 0, "closed_reason": 0, "other_reason": 0
        })

        for t in transfers:
            hour = t.created_at.hour
            hd = hour_data[hour]
            hd["total"] += 1
            if t.status == "completed":
                hd["completed"] += 1
            if store_id is not None:
                if t.source_store and t.source_store.id == store_id:
                    hd["outgoing"] += 1
                if t.target_store and t.target_store.id == store_id:
                    hd["incoming"] += 1
            else:
                hd["outgoing"] += 1
            if t.transfer_reason in ["busy", "room_unavailable"]:
                hd["busy_reason"] += 1
            elif t.transfer_reason == "temp_closed":
                hd["closed_reason"] += 1
            else:
                hd["other_reason"] += 1

        result = []
        for hour in range(9, 22):
            d = hour_data.get(hour, {
                "total": 0, "completed": 0, "outgoing": 0, "incoming": 0,
                "busy_reason": 0, "closed_reason": 0, "other_reason": 0
            })
            total = d["total"]
            result.append({
                "hour": f"{hour:02d}:00",
                "hour_num": hour,
                "total": total,
                "completed": d["completed"],
                "outgoing": d["outgoing"],
                "incoming": d["incoming"],
                "busy_reason": d["busy_reason"],
                "closed_reason": d["closed_reason"],
                "other_reason": d["other_reason"],
                "success_rate": round(d["completed"] / total * 100, 1) if total > 0 else 0
            })

        max_total = max((h["total"] for h in result), default=0)
        for h in result:
            h["heat_level"] = 0
            if max_total > 0:
                ratio = h["total"] / max_total
                if ratio >= 0.8:
                    h["heat_level"] = 4
                elif ratio >= 0.6:
                    h["heat_level"] = 3
                elif ratio >= 0.4:
                    h["heat_level"] = 2
                elif ratio >= 0.2:
                    h["heat_level"] = 1

        peak_hour = max(result, key=lambda x: x["total"]) if result else None

        weekday_map = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
        weekday_data = defaultdict(lambda: {"total": 0, "completed": 0})
        for t in transfers:
            wd = t.created_at.weekday()
            weekday_data[wd]["total"] += 1
            if t.status == "completed":
                weekday_data[wd]["completed"] += 1

        weekday_result = []
        for i in range(7):
            d = weekday_data.get(i, {"total": 0, "completed": 0})
            weekday_result.append({
                "weekday": weekday_map[i],
                "weekday_idx": i,
                "total": d["total"],
                "completed": d["completed"],
                "success_rate": round(d["completed"] / d["total"] * 100, 1) if d["total"] > 0 else 0
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

        peak_weekday = max(weekday_result, key=lambda x: x["total"]) if weekday_result else None

        return {
            "days": days,
            "hour_stats": result,
            "weekday_stats": weekday_result,
            "peaks": {
                "peak_hour": peak_hour,
                "peak_weekday": peak_weekday
            }
        }

    async def get_transfer_store_load(self, days: int = 7) -> dict:
        start_date = datetime.now() - timedelta(days=days)

        stores = await Store.objects.filter(status=True).all()
        result = []

        for store in stores:
            try:
                all_rooms = await store.fitting_rooms.all()
            except Exception:
                all_rooms = []
            active_rooms = [r for r in all_rooms if r.status != "sealed"]
            room_count = len(active_rooms)

            waiting_count = await QueueRecord.objects.filter(
                queue_time__gte=start_date,
                store__id=store.id,
                status="waiting"
            ).count()

            total_queue = await QueueRecord.objects.filter(
                queue_time__gte=start_date,
                store__id=store.id
            ).count()

            incoming = await StoreTransfer.objects.filter(
                created_at__gte=start_date,
                target_store__id=store.id
            ).count()

            incoming_completed = await StoreTransfer.objects.filter(
                created_at__gte=start_date,
                target_store__id=store.id,
                status="completed"
            ).count()

            outgoing = await StoreTransfer.objects.filter(
                created_at__gte=start_date,
                source_store__id=store.id
            ).count()

            outgoing_completed = await StoreTransfer.objects.filter(
                created_at__gte=start_date,
                source_store__id=store.id,
                status="completed"
            ).count()

            load_before = classify_load_level(waiting_count, room_count)
            adjusted_waiting = max(0, waiting_count + incoming_completed - outgoing_completed)
            load_after = classify_load_level(adjusted_waiting, room_count)

            net_inflow = incoming_completed - outgoing_completed
            transfer_ratio = round(
                (incoming_completed + outgoing_completed) / max(1, total_queue) * 100, 1
            )

            result.append({
                "store_id": store.id,
                "store_name": store.name,
                "floor": store.floor,
                "room_count": room_count,
                "waiting_count": waiting_count,
                "adjusted_waiting": adjusted_waiting,
                "total_queue": total_queue,
                "incoming_total": incoming,
                "incoming_completed": incoming_completed,
                "outgoing_total": outgoing,
                "outgoing_completed": outgoing_completed,
                "net_inflow": net_inflow,
                "load_before": load_before,
                "load_before_text": LOAD_LEVEL_TEXT.get(load_before, load_before),
                "load_after": load_after,
                "load_after_text": LOAD_LEVEL_TEXT.get(load_after, load_after),
                "load_improved": load_after != load_before and (
                    (load_before == "critical" and load_after != "critical") or
                    (load_before == "high" and load_after in ["medium", "low"]) or
                    (load_before == "medium" and load_after == "low")
                ),
                "transfer_ratio": transfer_ratio,
                "balance_score": round(
                    max(0, 100 - abs(net_inflow) * 10) - (
                        20 if load_after == "critical" else
                        10 if load_after == "high" else 0
                    ), 1
                )
            })

        result.sort(key=lambda x: x["total_queue"], reverse=True)

        summary = {
            "total_incoming": sum(r["incoming_total"] for r in result),
            "total_outgoing": sum(r["outgoing_total"] for r in result),
            "total_completed_incoming": sum(r["incoming_completed"] for r in result),
            "total_completed_outgoing": sum(r["outgoing_completed"] for r in result),
            "stores_improved": sum(1 for r in result if r["load_improved"]),
            "avg_balance_score": round(
                sum(r["balance_score"] for r in result) / len(result), 1
            ) if result else 0
        }
        summary["net_flow"] = summary["total_completed_incoming"] - summary["total_completed_outgoing"]

        return {
            "days": days,
            "summary": summary,
            "store_loads": result
        }

    async def get_transfer_heatmap(self, days: int = 14) -> dict:
        start_date = datetime.now() - timedelta(days=days)

        transfers = await StoreTransfer.objects.filter(
            created_at__gte=start_date,
            status="completed"
        ).select_related("source_store", "target_store").all()

        stores = await Store.objects.filter(status=True).order_by("floor").all()
        store_names = [s.name for s in stores]
        store_ids = [s.id for s in stores]

        matrix = [[0 for _ in store_ids] for _ in store_ids]

        for t in transfers:
            if t.source_store and t.target_store:
                try:
                    src_idx = store_ids.index(t.source_store.id)
                    tgt_idx = store_ids.index(t.target_store.id)
                    matrix[src_idx][tgt_idx] += 1
                except ValueError:
                    pass

        max_count = 0
        for row in matrix:
            for v in row:
                if v > max_count:
                    max_count = v

        heatmap_matrix = []
        for i, src_name in enumerate(store_names):
            for j, tgt_name in enumerate(store_names):
                count = matrix[i][j]
                if i == j:
                    continue
                heat_level = 0
                if max_count > 0:
                    ratio = count / max_count
                    if ratio >= 0.8:
                        heat_level = 4
                    elif ratio >= 0.6:
                        heat_level = 3
                    elif ratio >= 0.4:
                        heat_level = 2
                    elif ratio >= 0.2:
                        heat_level = 1
                heatmap_matrix.append({
                    "source_store": src_name,
                    "source_store_id": store_ids[i],
                    "target_store": tgt_name,
                    "target_store_id": store_ids[j],
                    "transfer_count": count,
                    "heat_level": heat_level,
                    "is_top_route": count > 0 and count == max_count
                })

        floor_routes = defaultdict(lambda: {"same_floor": 0, "cross_floor": 0, "upstairs": 0, "downstairs": 0})
        for t in transfers:
            if t.source_store and t.target_store:
                src_floor = t.source_store.floor
                tgt_floor = t.target_store.floor
                store_pair = f"{min(src_floor, tgt_floor)}-{max(src_floor, tgt_floor)}"
                if src_floor == tgt_floor:
                    floor_routes[store_pair]["same_floor"] += 1
                else:
                    floor_routes[store_pair]["cross_floor"] += 1
                    if tgt_floor > src_floor:
                        floor_routes[store_pair]["upstairs"] += 1
                    else:
                        floor_routes[store_pair]["downstairs"] += 1

        floor_result = []
        for pair, stats in floor_routes.items():
            total = stats["same_floor"] + stats["cross_floor"]
            floor_result.append({
                "floor_pair": f"{pair}层",
                "floors": pair,
                "total": total,
                "same_floor": stats["same_floor"],
                "cross_floor": stats["cross_floor"],
                "upstairs": stats["upstairs"],
                "downstairs": stats["downstairs"]
            })
        floor_result.sort(key=lambda x: -x["total"])

        return {
            "days": days,
            "stores": [{"id": s.id, "name": s.name, "floor": s.floor} for s in stores],
            "heatmap": [h for h in heatmap_matrix if h["transfer_count"] > 0],
            "max_transfer_count": max_count,
            "floor_routes": floor_result
        }


stats_service = StatsService()
