
from common.settings import HBP_SECRET_KEY, HBP_ACCESS_KEY
from api.quant_api import TradeAccount, to_dataframe, to_dict, get_bars_local, Indicator, Tick, Order, Bar
import time
import pandas as pd
import numpy as np
import api.connection as conn
from api.fund_perform_eval import PerformEval


def tradelog(account=None):

    account.get_orders_by_symbol(sec_id = 'btcusdt')


def clearing(account=None, interval='1day', ctime='00:00:00'):
    '''
    定期进行清结算
    :param interval: 支持两种方式，interval='1day' 每天结算一次，interval='60min' 每小时结算一次
    :param ctime: 指定每天具体时间
    :return:
    '''

    while (1):
        isStart = False
        now = time.localtime(time.time())
        if interval == '1day':
            # 每日 00:00:00 进行清算
            if now.tm_hour == 0 and now.tm_min == 0:
                isStart = True
        elif interval == '60min' or interval =='1hour':
            # 每小时清算一次，XX:00:00 进行结算
            if now.tm_min == 0:
                isStart = True

        if isStart:
            positions = account.get_positions(source='margin')
            hist_position = hist_position + [positions]
            netvalue = to_dataframe(hist_position)
            myindicator = Indicator()
            perform = PerformEval(netvalue)


if __name__ == '__main__':

    initial_amount = 100000
    hbaccount = TradeAccount(exchange='hbp', api_key=HBP_ACCESS_KEY,api_secret=HBP_SECRET_KEY, currency='USDT')
    currency = hbaccount.currency.lower()

    # 普通账户数量
    positions = hbaccount.get_positions(source='spot')
    pos_df = to_dataframe(positions)
    # print(pos_df)

    # 借贷账户数量
    positions = hbaccount.get_positions(source='margin')
    pos_df2 = to_dataframe(positions)
    # print(pos_df2)

    pos_df = pos_df.append(pos_df2)

    # 统计总的持仓
    pos_df = pos_df.fillna(0)
    pos_df['netvol'] = pos_df['available'] + pos_df['frozen'] + pos_df['loan'] + pos_df['interest']
    pos_df['price'] = 0

    pos_df = pos_df[pos_df['netvol'] != 0]
    pos_df.index = pos_df['sec_id']
    print(pos_df)

    # 获取每只币种当前价格
    sec_price = {}
    sec_price[currency] = 1
    sec_ids = list(set(np.unique(pos_df.index)) - set([currency]))
    symbols = [each + currency for each in sec_ids]
    sec_ticks = hbaccount.get_last_ticks(','.join(symbols))
    for each in sec_ticks:
        each_sec = each.sec_id.replace(currency, '')
        sec_price[each_sec] = each.last_price

    print(sec_price)

    pos_df['price'] = [sec_price[each] for each in pos_df.index]
    pos_df['netamt'] = pos_df['netvol']*pos_df['price']
    print(pos_df)

    pos_result = pos_df[['account_type', 'available', 'frozen', 'loan', 'interest', 'netvol', 'price', 'netamt']]
    pos_result.columns = ['账户类型', '可用', '冻结', '待还借贷', '待还利息', '净持仓量', '当前价格', '净额']
    print("当前持仓明细：")
    print(pos_result)
    total_amount = pos_result['净额'].sum()
    print("当前总持仓额为：", total_amount)
    print("当前净值为：", total_amount/initial_amount)
