'''
Those Alphas come from the paper: https://arxiv.org/ftp/arxiv/papers/1601/1601.00991.pdf。
Cause there's some unclear definitions from the paper, we also take the JoinQuant's implementation(https://www.joinquant.com/data/dict/alpha101) as a reference.
'''

from backtrader.indicators import Highest, StdDev, Indicator
from backtrader.functions import If
from scipy import stats
import numpy as np

class Rank(Indicator):
    lines = ('rank',)
    params = (('period', 20),)

    def next(self):
        values = self.data.get(size=self.p.period)
        if len(values) > 0:
            self.lines.rank[0] = float(stats.rankdata(values)[-1])
        else:
            self.lines.rank[0] = 0


class Returns(Indicator):
    lines = ('returns',)
    params = (('period', 1),)

    def next(self):
        self.lines.returns[0] = (self.data[0] - self.data[-self.p.period]) / self.data[-self.p.period]


class WQA1(Indicator):
    '''
    Alpha#1: (rank(Ts_ArgMax(SignedPower(((returns < 0) ? stddev(returns, 20) : close), 2.), 5)) - 0.5)
    这是一个较为复杂的因子,我们一步一步拆解:
    - returns < 0 是判断每日收益是否小于0的条件语句,也就是该股票是否出现下跌。
    - stddev(returns, 20) 计算最近20天的收益标准差。
    - ?: 是一个条件运算符,如果条件成立,输出冒号前面的语句,否则输出冒号后面的语句。
    - 所以如果当日股价下跌,则取最近20天收益标准差;如果没有下跌,则取当日收盘价close。
    - SignedPower(x, 2.) 计算x的平方。
    - Ts_ArgMax(x, 5) 取x在最近5天里的最大值所在的日期。
    - rank(x)计算x的排名,在这里是排在最近5天的最大值中所排名。
    - 减去0.5是为了中心化排名值。
    总体来看,这个因子是检测股价在最近5天里是否出现了大幅下跌,如果有,产生 trading signal。它利用了20天收益标准差来检测异常下跌。
    问题：
    - stddev 和 close 量纲不同，如何能比？
    - SignedPower 不改变符号方向，后续使用结果进行 Ts_ArgMax，那么 SignedPower 毫无意义

    '''
    lines = ('wqa1', 'signed_power', 'ts_argmax', 'rank')
    params = (('period', 20),)

    plotlines = dict(
        signed_power=dict(_plotskip=True), ts_argmax=dict(_plotskip=True), rank=dict(_plotskip=True),
    )


    def __init__(self):
        self.addminperiod(self.params.period)
        self.rets = Returns(self.data)
        self.stddev = StdDev(self.rets, period=self.params.period)

    def next(self):
        val = self.rets[0] if self.rets[0] < 0 else self.data.close[0]
        self.signed_power[0] = pow(val, 2.)
        self.ts_argmax[0] = np.nanargmax(self.signed_power.get(size=5))
        self.rank[0] = stats.rankdata(self.ts_argmax.get(size=5))[-1]
        self.lines.wqa1[0] = self.rank[0] - 0.5



class WQA2(Indicator):
    '''
    Alpha#2: (-1 * correlation(rank(delta(log(volume), 2)), rank(((close - open) / open)), 6))

    这是一个利用成交量和价格的数据因子。
    - delta(log(volume), 2) 计算对数成交量的2日变化量。
    - rank(...) 对其进行排名。
    - (close - open) / open 计算开盘至收盘的价格变化幅度。
    - 对其排名。
    - correlation(.., .., 6) 计算这两者在过去6日的相关系数。
    - 加上-1使其方向与我们的交易信号一致。
    这个因子的基本思想是,利用价格与成交量的RANK信息,来发现一致或相反的趋势,作为交易信号。
    
    问题：
    - 若要计算最近 6 天的相关性，考虑成交量是需要计算两天之差，因此 indicator 中的 period 需要多加一天。即为 7 。
    - 由于 volume 成交量可能为 0， 因此该因子计算出来的值可能为 -inf。 可以通过对于 volume 增加一个 10e-5 的偏移量解决该问题，但当前代码中，未进行该特殊处理。
    '''
    lines = ('wqa2', )
    params = (('period', 7),)

    def __init__(self):
        self.addminperiod(self.params.period)

    def next(self):
        closes = self.data.close.get(size=self.p.period)
        opens = self.data.open.get(size=self.p.period)
        volumes = self.data.volume.get(size=self.p.period)

        # Calculate the rank of delta(log(volume), 2)
        volume_changes = np.diff(np.log(volumes))
        volume_rank = stats.rankdata(volume_changes)

        # Calculate the rank of (close - open) / open
        price_changes = np.divide(np.subtract(closes, opens), opens)[1:]
        price_rank = stats.rankdata(price_changes)

        # Calculate the correlation
        correlation = np.corrcoef(volume_rank, price_rank)[0, 1]

        # Set the value of alpha2
        self.lines.wqa2[0] = -1 * correlation



class WQA3(Indicator):
    '''
    Alpha#3: (-1 * correlation(rank(open), rank(volume), 10))

    这个因子计算的是开盘价的排名和交易量的排名在过去10天内的相关性，并取负值。
    这是一个利用开盘价和成交量的简单因子。
    - rank(open) 对开盘价进行排名
    - rank(volume) 对成交量进行排名
    - correlation(.., .., 10) 计算两者在过去10日的相关性
    - 加上-1使信号方向与我们的交易信号一致
    - 这个因子的思路是,检测开盘价和成交量的排名是否存在相关性,以发现异常的模式。

    从这个简单的因子我们可以看到:
    - 排名转换能标准化不同量,便于比较
    - 相关性計算可以检测变量间的相关依赖
    - 增加一个-1系数控制信号方向
    这些都是构建因子时常用的技巧。
    '''
    lines = ('wqa3',)
    params = (('period', 10),)

    def __init__(self):
        self.addminperiod(self.p.period)
        
    def next(self):
        rank_open = stats.rankdata(self.data.open.get(size=self.p.period))
        rank_volume = stats.rankdata(self.data.volume.get(size=self.p.period))
        self.lines.wqa3[0] = -1 * np.corrcoef(rank_open, rank_volume)[0, -1]


class WQA4(Indicator):
    '''
    Alpha#4: (-1 * Ts_Rank(rank(low), 9))
    这个因子的计算涉及到两个函数：Ts_Rank 和 rank。Ts_Rank 是时间序列排名函数，rank 是普通的排名函数。low 是股票的最低价。
    这是一个利用最低价的简单因子。
    - rank(low) 对最低价进行排名
    - Ts_Rank(.., 9) 计算最近9日的排名时序
    - 加上-1调整信号方向

    这个因子的思路是:
    - 检测最低价在最近一段时间内的时序排名
    - 当最低价排名下降时生成卖出信号
    它反映了跌势的持续。

    问题：
    - 当对于一个窗口上最末尾的值时，ts_rank 和 rank 计算出的结果是等价的。因此，该公式中的 ts_rank 似乎并没有独特意义。

    '''
    lines = ('wqa4',)
    params = (('period', 9),)

    def __init__(self):
        self.addminperiod(self.params.period)

    def next(self):
        values = self.data.low.get(size=self.p.period)
        ranks = stats.rankdata(values)
        ts_rank = np.argsort(ranks)[-1]
        self.lines.alpha4[0] = -1 * ts_rank
