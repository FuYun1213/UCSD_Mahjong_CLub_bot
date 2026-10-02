Object.assign(window.MahjongI18n.entries,{
reservationStart:['开始时间','Starts'],reservationEnd:['结束时间','Ends'],
reservationEndMonth:['结束月','End Month'],reservationEndDay:['结束日','End Day'],reservationEndClock:['结束时间','End Time'],
reservationResetDuration:['恢复默认时长','Reset to One Hour'],
reservationRangeDisplay:['{start} 至 {end}','{start} – {end}'],
reservationSession:['预约场次','Reservation Session'],reservationPersonalDetails:['个人预约详情','Individual Reservations'],
reservationNearbySelected:['附近已有预约使用第 {table} 桌，已为你默认选择此桌。','A nearby reservation is already using Table {table}. This table has been selected by default.'],
reservationNearbyRespect:['已保留你手动选择的桌子。','Your selected table will be kept.'],
reservationResolving:['正在核对预约时间…','Checking reservation times…'],
reservationRetryTimes:['重新核对时间','Retry Time Check'],
reservationResolveRequired:['预约时间尚未核对成功，请重试后保存。','The reservation time has not been checked. Retry before saving.'],
invalid_reservation_end:['结束时间必须晚于开始时间，请检查结束日期和时间。','The end must be after the start. Check its date and time.'],
reservation_end_before_start:['结束时间必须晚于开始时间，请检查结束日期和时间。','The end must be after the start. Check its date and time.'],
reservation_session_full:['这个预约场次已经满员，请选择其他桌子或时间。','This reservation session is full. Choose another table or time.']
});

Object.assign(window.MahjongI18n.entries,{
reservationGameMode:['参加方式','Participation'],reservationFiniteGames:['指定局数','Set number of games'],reservationPlannedGames:['参加对局数','Number of games'],reservationAnyGames:['任意','Any'],reservationChooseGames:['请选择局数','Choose games'],reservationPlannedGamesHelp:['一局是一场完整对局；预计结束时间由系统计算。','One game is a complete match. End times are estimates calculated by the system.'],invalid_planned_games:['请输入正整数局数。','Enter a positive whole number of games.'],reservationHistory:['预约历史','Reservation history'],reservationLegacyNeedsAssignment:['旧预约局数未知，需管理员确认后才能加入队列。','Legacy game count is unknown; an administrator must assign it before queueing.'],
queueSuggestedArrival:['建议到场时间：{time}。人数不足，仅供预约参考。','Suggested arrival: {time}. The batch is short of players, so this is only a booking suggestion.'],queueNextTable:['下一桌','Next table'],queueEstimatedStart:['预计开始','Estimated start'],queueTimeUnknown:['时间待定','Time pending'],queueNoDuration:['尚无可靠实际对局时长，暂不显示预计开桌时间。','No reliable actual game durations yet, so an estimated start time is unavailable.'],queueStatus_tentative:['暂定','Tentative'],queueStatus_provisional:['暂定','Tentative'],queueStatus_pending:['暂定','Tentative'],queueStatus_notified:['已通知','Notified'],queueStatus_started:['已开始','Started'],queueStatus_completed:['已完成','Completed'],queueStatus_waiting:['等待中','Waiting'],queueMissing:['还缺 {count} 人；开桌时间尚未确定。','{count} more players needed; start time is unconfirmed.'],queueMissingOne:['还缺 1 人；开桌时间尚未确定。','1 more player needed; start time is unconfirmed.'],queueNoBatch:['尚未形成下一批。','No next batch yet.'],queueWaiting:['后续等待队列','Later waiting queue'],queueNoWaiting:['暂无后续等待玩家。','No later players waiting.'],queueRemaining:['剩余 {count} 局','{count} games left'],queueNeedsAssignment:['局数待管理员确认','Games need admin assignment'],queueDragHint:['长按拖动调整尚未开始的队列顺序。','Press and hold to drag players into order.'],queueDragHandle:['长按拖动 {name}','Press and hold to move {name}'],queueSaved:['队列顺序已保存。','Queue order saved.'],queue_stale_version:['队列已被他人修改，请核对最新顺序。','The queue changed on another device. Review the latest order.']
});
