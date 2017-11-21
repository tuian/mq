#   2014-07-08  Normaneil E. Macutay <normanm@remotestaff.com.au>
#   -   task to get the total log hours of staff based on start and end date


import settings
import couchdb


from persistent_mysql_connection import engine
from sqlalchemy.sql import text

from celery.task import task, Task
from celery.execute import send_task
from celery.task.sets import TaskSet
from celery import Celery
import sc_celeryconfig


from datetime import date, datetime, timedelta
import pytz
from pytz import timezone
from decimal import Decimal, ROUND_HALF_UP
import calendar
import logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(message)s')

import locale
locale.setlocale(locale.LC_ALL, 'en_US.UTF-8')


TWOPLACES = Decimal(10) ** -2

def get_ph_time(as_array=False):
    """returns a philippines datetime
    """
    utc = timezone('UTC')
    phtz = timezone('Asia/Manila')
    now = utc.localize(datetime.utcnow())
    now = now.astimezone(phtz)
    if as_array:
        return [now.year, now.month, now.day, now.hour, now.minute, now.second]
    else:
        return datetime(now.year, now.month, now.day, now.hour, now.minute, now.second)

@task            
def get_total_adj_hrs_per_month(conn, sid, date_search):
    str=""
    data={}
    for d in date_search:
        d = datetime.strptime(d, '%Y-%m-%d')  
        end_date = datetime(d.year, d.month, calendar.mdays[d.month])
        
        #str += '%s %s' % (d.strftime('%Y-%m-%d'), end_date.strftime('%Y-%m-%d'))
        total_adj_hrs = get_total_adj_hrs(conn, sid, d, end_date)
        data['%s' % d.strftime('%m/%Y')] = total_adj_hrs
    return data    

    
@task    
def get_total_adj_hrs(conn, sid, start_date, end_date):
    """
    conn, a mysql connector, was also passed to ease out connect/disconnects
    """
    
    total_hrs = Decimal('0.00')
    x = start_date
    start_date_ts = date(x.year, x.month, 1)

    #get all involved timesheet
    sql = text("""
        SELECT id, month_year FROM timesheet
        WHERE status IN ('open', 'locked')
        AND subcontractors_id = :sid
        AND month_year BETWEEN :start_date AND :end_date
    """)
    timesheets = conn.execute(sql, sid=sid, start_date=start_date_ts, end_date=end_date).fetchall()

    for ts in timesheets:
        sql = text("""
            SELECT day, adj_hrs FROM timesheet_details
            WHERE timesheet_id = :tid
            ORDER BY day
        """)
        ts_details = conn.execute(sql, tid=ts.id).fetchall()

        for ts_detail in ts_details:
            x = ts.month_year
            y = datetime(x.year, x.month, ts_detail.day)
            if (y >= start_date) and (y <= end_date):
                if ts_detail.adj_hrs == None:
                    continue
                adj_hrs = Decimal('%0.2f' % ts_detail.adj_hrs)
                total_hrs += adj_hrs


    return "%0.2f" % total_hrs
    


@task(ignore_result=True)
def process_doc_id(doc_id):
    logging.info('checking %s' % doc_id)
    s = couchdb.Server(settings.COUCH_DSN)
    
    
    #send notice to devs
    now = get_ph_time(as_array=False) 
    to=['devs@remotestaff.com.au']
    couch_mailbox = s['mailbox']    
    date_created = [now.year, now.month, now.day, now.hour, now.minute, now.second]          
    mailbox = dict(
        sent = False,        
        bcc = None,
        cc = None,
        created = date_created,
        generated_by = 'celery subcon_total_adj_hours.process_doc_id',
        html = None,
        text = 'executing subcon_total_adj_hours.process_doc_id %s' % doc_id,        
        subject = 'executing subcon_total_adj_hours.process_doc_id %s' % doc_id,
        to = to            
    )
    mailbox['from'] = 'noreply@remotestaff.com.au'        
    #couch_mailbox.save(mailbox)    
    
    
    
    db = s['subconlist_reporting']
    doc = db.get(doc_id)
    if doc == None:
        raise Exception('subconlist_reporting document not found : %s' % doc_id)
        
    subcontractor_ids = doc['subcontractor_ids']
    start_date = doc['start_date']
    end_date = doc['end_date']    

    start_date = datetime.strptime(start_date, '%Y-%m-%d')
    end_date = datetime.strptime(end_date, '%Y-%m-%d')

    page_usage=""
    if 'page_usage' in doc:    
        page_usage = doc['page_usage']
    
    #return page_usage    
            
    conn = engine.connect()    
    total_adj_hrs_result={}

    for sid in subcontractor_ids:
        userid =  doc['subcon_userid'][sid]
        if page_usage == 'soa':
            total_adj_hrs = get_total_adj_hrs_per_month(conn, sid, doc['date_search'])    
        else:
            total_adj_hrs = get_total_adj_hrs(conn, sid, start_date, end_date)                                 
        total_adj_hrs_result[int(sid)] = total_adj_hrs        
        
    doc['total_adj_hrs_result'] = total_adj_hrs_result
    #return doc['total_adj_hrs_result']
    conn.close()    
    db.save(doc)
    if page_usage != 'soa':    
            
        if settings.DEBUG:
            send_task("subcon_total_log_hours.process_doc_id", [doc_id])
        else:
            celery = Celery()
            celery.config_from_object(sc_celeryconfig)
            celery.send_task("subcon_total_log_hours.process_doc_id", [doc_id])
                    
    
if __name__ == '__main__':
    logging.info('tests')
    logging.info(process_doc_id('70b522f1d49d00874f41c9644b00d43d'))
