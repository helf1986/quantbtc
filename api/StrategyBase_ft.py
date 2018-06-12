# -*- coding: utf-8 -*-
"""
Created on Wed Apr 25 16:02:09 2018

@author: ShuangJi.He
"""
from __future__ import division
#from gmsdk import to_dict,md
#md.init('18512101480', 'Hsj123')
import os
from api.quant_api import TradeAccount, get_bars_local
from api.quant_api import to_dict
from api import logger
import time
# from queue import Queue
import threading

from multiprocessing import Process, Queue
import json
import math
import api.connection as conn
import pandas as pd


#~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
'''
ft版本拓展为多品种/多周期的事件订阅，每个bar事件对应一个品种的一个周期，并以此驱动基于此K线的多策略
*注意：单策略在不同周期需要重新生成文件并不同命名
'''
#


#-----交易的基类---------
class Strategy(object):

    def __init__(self, name=''):

        self.prt    = True          # 是否启动基类中的打印
        self.name   = name
        self.MarketPosition = 0     # 策略仓位记录

        self.__barcount = 0            # 记录当前推送bar数
        self.__type     = 'history'  # 数据状态,用以区分历史数据还是实时数据。默认'history'，满足条件后赋值为'realtime'

        self.__orderqueue   = Queue()   # 记录队列，对应处理函数on_order
        self.__monitorqueue = Queue()     # monitor记录队列，对应处理函数on_monitor

        # ====================================================
        '''
        等待回调 ：以下内容需要在cerebro中add函数里进行赋值，并之后调用initialtion函数进行初始化     
        '''
        self.api            = None      # 交易账户接口
        self.module         = None
        self.margin_currency = None
        self.account        = None
        self.symbol_list    = None
        self.bar_type       = None
        self.backbarnum     = None

        self.filename       = ''
        self.monitordata    = ''

    def initialtion(self):
        '''
        实时监控文件名
        监控数据格式
        '''        
        self.filename=self.account + '_' + self.name + '_' + self.module + "2" + self.margin_currency + '.json'
        '''
        实时生存，与monitor文件夹中交互
        margin_flag:是否有未还融资融券,也是读写标识
        margin_type:当前融资融券申请类型，1=借贷申请apply_margin，0=还贷申请repay_margin
        margin_order_id：申请操作函数的返回编号
        '''
        self.monitordata={"account"     : self.account,
                          "commdity"    : self.symbol_list,
                          "module"      : self.module,
                          "MarketPosition":self.MarketPosition,
                          "unit"        : 0,
                          "enterprice"  : None,
                          "margin_flag" : False,
                          "margin_type" : None,
                          "margin_order_id" : None
                          }
        
#-----------------eventprocess函数-----------------    
    '''
       交易类
       交易注意事项：
       1、price只接受2位小数，需要处理
       2、volumne最小交易单位btc=0.001，usdt=0.001(最小额度100)，
       但是融资融券利息需要|只接受8位小数，，需要额外处理
       3、融资融券操作如下，需要有函数定期执行余钱和余券管理
           *融券操作：买券还券需要多买，存部分余券
           *融资操作需要多融，卖券还款需要多卖，存部分余钱
           *融券余券管理可以清零，无条件
           *融资余钱管理也可以清零，但账户需要预留部分本金，应对交易时价格波动，建议一开始为账户5%，即卖出5%的btc
    '''

    def buy(self,unit, price):
        '''
        分原来是否持仓，是则先平后进
        '''
        price=round(price,2)#报单只接受，两位有效数字    
        if self.MarketPosition==-1:
            self.MarketPosition=0;logger.info (self.name+"pre_buytocover(%s,%s)"%(unit,price))            
            if self.__type=='realtime':
                if self.module=='usdt':
                    '''
                    还券分三步：
                    1、确认融券量=本币+利息
                    2、买入足够数量券【可以执行拆单函数】
                    3、执行还券流程
                    '''                    
                    unpaid_volume=self.api.get_margin_volume(self.monitordata['margin_order_id'],self.symbol_list,currency=self.margin_currency)
                    unpaid_volume=round(unpaid_volume,8)#8位小数
                    trade_volume=math.ceil(unpaid_volume*1000)/1000
                    order=self.api.open_long( source='margin', sec_id=self.symbol_list, price=price, volume=trade_volume)   
                    marginid=self.api.repay_margin( order_id=self.monitordata['margin_order_id'], amount=unpaid_volume)                                                           
                    self.monitordata['MarketPosition']=self.MarketPosition
                    self.monitordata['unit']=unit
                    self.monitordata['enterprice']=price
                    self.monitordata['margin_type']=0
                    self.monitordata['margin_order_id']=marginid
                    self.__monitorqueue.put(self.monitordata)
                else:
                    order=self.api.open_long(exchange=self.monitordata['margin_order_id'], source='margin', sec_id=self.symbol_list, price=price, volume=unit)
                self.__orderqueue.put(order)

        if self.MarketPosition==0:
            self.MarketPosition=1;logger.info (self.name+"buy(%s,%s)"%(unit,price),'Marketposition=%s'%(self.MarketPosition) )     
            if self.__type=='realtime':
                if self.module=='usdt':
                    order=self.api.open_long( source='margin', sec_id=self.symbol_list, price=price, volume=unit)
                else: 
                    money=100 if price*unit<=100  else  math.ceil(price*unit*1000)/1000        
                    marginid=self.api.apply_margin( symbol=self.symbol_list, currency=self.margin_currency, amount=money)
                    order=self.api.open_long( source='margin', sec_id=self.symbol_list, price=price, volume=unit)                     
                    self.monitordata['MarketPosition']=self.MarketPosition
                    self.monitordata['unit']=unit
                    self.monitordata['enterprice']=price
                    self.monitordata['margin_type']=1
                    self.monitordata['margin_order_id']=marginid
                    self.__monitorqueue.put(self.monitordata)
                self.__orderqueue.put(order)                  
                msg = " 开多仓 "+self.symbol_list+"@ %s,%f" % (unit, price)
                logger.info(msg)


    def order_vwap(self, order_side=1, price_type='limit'):
        pass


    def sellshort(self,unit,price):
        price=round(price,2)#报单只接受，两位有效数字  
        if self.MarketPosition==1:   
            self.MarketPosition=0;logger.info (self.name+"pre_sell(%s,%s)"%(unit,price) )           
            if self.__type=='realtime':
                if self.module=='usdt':
                    order=self.api.close_long(source='margin', sec_id=self.symbol_list, price=price, volume=unit)  
                else:
                    money=self.api.get_margin_volume(self.monitordata['margin_order_id'],self.symbol_list,currency=self.margin_currency)
                    money=round(money,8)
                    trade_volume=math.ceil(money/price*1000)/1000
                    order=self.api.close_long( source='margin', sec_id=self.symbol_list, price=price, volume=trade_volume)   
                    marginid=self.api.repay_margin( order_id=self.monitordata['margin_order_id'], amount=money)                                       
                    self.monitordata['MarketPosition']=self.MarketPosition
                    self.monitordata['unit']=unit
                    self.monitordata['enterprice']=price
                    self.monitordata['margin_type']=0
                    self.monitordata['margin_order_id']=marginid
                    self.__monitorqueue.put(self.monitordata)
                self.__orderqueue.put(order)  
        if self.MarketPosition==0:
            self.MarketPosition=-1;logger.info (self.name+"sellshort(%s,%s)"%(unit,price),'Marketposition=%s'%(self.MarketPosition) )
            if self.__type=='realtime':
                if self.module=='usdt':
                    marginid=self.api.apply_margin( symbol=self.symbol_list, currency=self.margin_currency, amount=unit)
                    order=self.api.close_long( source='margin', sec_id=self.symbol_list, price=price, volume=unit)   
                    self.monitordata['MarketPosition']=self.MarketPosition
                    self.monitordata['unit']=unit
                    self.monitordata['enterprice']=price
                    self.monitordata['margin_type']=1
                    self.monitordata['margin_order_id']=marginid
                    self.__monitorqueue.put(self.monitordata)                    

                else:
                    order=self.api.close_long( source='margin', sec_id=self.symbol_list, price=price, volume=unit)   
                    
                self.__orderqueue.put(order)  
                msg = " 开空仓 "+self.symbol_list+"@ %s,%f" % (unit, price)
                logger.info(msg)


    def sell(self,unit,price):
        price=round(price,2)#报单只接受，两位有效数字  
        if self.MarketPosition==1:
            self.MarketPosition=0;logger.info (self.name+"sell(%s,%s)"%(unit,price),'Marketposition=%s'%(self.MarketPosition))
            if self.__type=='realtime':
                if self.module=='usdt':
                    order=self.api.close_long(source='margin', sec_id=self.symbol_list, price=price, volume=unit)  
                else: 
                    money=self.api.get_margin_volume(self.monitordata['margin_order_id'],self.symbol_list,currency=self.margin_currency)
                    money=round(money,8)
                    trade_volume=math.ceil(money/price*1000)/1000
                    order=self.api.close_long(source='margin', sec_id=self.symbol_list, price=price, volume=trade_volume)   
                    marginid=self.api.repay_margin( order_id=self.monitordata['margin_order_id'], amount=money)                                       
                    self.monitordata['MarketPosition']=self.MarketPosition
                    self.monitordata['unit']=unit
                    self.monitordata['enterprice']=price
                    self.monitordata['margin_type']=0
                    self.monitordata['margin_order_id']=marginid
                    self.__monitorqueue.put(self.monitordata)
                self.__orderqueue.put(order)  
                msg = " 平多仓 "+self.symbol_list+"@ %s,%f" % (unit, price)
                logger.info(msg)


    def buytocover(self,unit,price):
        price=round(price,2)#报单只接受，两位有效数字  
        if self.MarketPosition==-1:
            self.MarketPosition=0;logger.info (self.name+"buytocover(%s,%s)"%(unit,price),'Marketposition=%s'%(self.MarketPosition))
            if self.__type=='realtime':
                if self.module=='usdt':
                    unpaid_volume=self.api.get_margin_volume(self.monitordata['margin_order_id'],self.symbol_list,currency=self.margin_currency)
                    unpaid_volume=round(unpaid_volume,8)#8位小数
                    trade_volume=math.ceil(unpaid_volume*1000)/1000
                    order=self.api.open_long( source='margin', sec_id=self.symbol_list, price=price, volume=trade_volume)   
                    marginid=self.api.repay_margin( order_id=self.monitordata['margin_order_id'], amount=unpaid_volume)                                       
                    self.monitordata['MarketPosition']=self.MarketPosition
                    self.monitordata['unit']=unit
                    self.monitordata['enterprice']=price
                    self.monitordata['margin_type']=0
                    self.monitordata['margin_order_id']=marginid
                    self.__monitorqueue.put(self.monitordata)
                else:
                    order=self.api.close_long( source='margin', sec_id=self.symbol_list, price=price, volume=unit)   
                self.__orderqueue.put(order)  
                msg = " 平空仓 "+self.symbol_list+"@ %s,%f" % (unit, price)
                logger.info(msg)

    '''
    基准类
    '''
    def on_bar(self,bar):
        '''
        barcount必须更新以识别历史数据和实时数据
        '''                   
        self.__barcount+=1           
        if self.prt:
            print (u"执行中.....sec=%s, strtime=%s, close=%.4f, volume=%.4f, barcount=%s, type=%s"%(bar.sec_id,bar.strtime, bar.close, bar.volume, self.__barcount,self.__type) )

        '''
        历史bar全部遍历，开始实时数据推送;
        1、数据标记改为'realtime',最后一步    
        2、数据库读取当前融资融券id，如果有的话
        3、输出策略启动信息手机
        '''
        if self.__barcount==self.backbarnum:
            '''
            以下内容仅在历史数据推送完后执行一次
            '''
            if self.__type=='history':
                #-------------step 2-----------------
                file='monitor/'+self.filename
                if not os.path.exists(file):#无文件则新建文件
                    with open(file, 'w') as f:
                        json.dump(self.monitordata, f)
                else:
                    with open(file, 'r') as f:      
                        temp=json.load(f)
                        if temp['margin_flag']:#读取标识开启
                            self.monitordata=temp
                            
                #--------------step 3--------------
                msg = " Strategy(%r) on [%s,%s] is restarting @%s ...MarketPosition=%s" % (self.name, self.module,self.margin_currency,time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),self.MarketPosition)
                logger.info(msg)

                #--------------step 1--------------
                print (u"history data feeded successfully...")
                print (u"realtime data on going...")
                self.__type='realtime'


    def orderprocess(self):
        while True:
            try:
                order=self.__orderqueue.get_nowait() 
                self.on_order(order)
                time.sleep(0.5)
            except:
                return "no more order..."


    def monitorprocess(self):
        while True:
            try:
                monitor=self.__monitorqueue.get_nowait() 
                self.on_monitor(monitor)
                time.sleep(0.5)
            except:
                return "no more monitor..."


    def on_order(self, order):
        '''
        此处处理输出order到数据库，包括历史表和实时表
        '''
        try:
            conn.order2db(order)
        except:
            logger.warn('订单号写入数据库失败！')
        pass


    def on_monitor(self, monitor):
        if monitor['margin_order_id']==0:
            print ("Margin error！！！")
            return

        # 融资融券开仓
        if monitor["margin_type"]==1:
            #更新监控文件
            monitor['margin_flag']=True
            self.monitordata['margin_flag'] = monitor['margin_flag']
            file='monitor/'+self.filename

            with open(file, 'w') as f:
                json.dump(self.monitordata, f)

        # 融资融券平仓
        elif monitor["margin_type"]==0:
            # 更新监控文件
            monitor['margin_flag']=False
            self.monitordata['margin_flag']=monitor['margin_flag']
            file='monitor/'+self.filename
            with open(file, 'w') as f:
                json.dump(self.monitordata, f)   

#================================================================


if __name__ == '__main__':
    
    #定义策略
    mystr1=Strategy(name="StrategyBase1")
    mystr2=Strategy(name="StrategyBase2")
