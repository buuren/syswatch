import os
import time
from datetime import timedelta
import json
import resource


class Processes:
    def __init__(self, observer):
        self.observer = observer


class CPUStats:
    def __init__(self, observer):
        self.sector_size = 1
        self.observer = observer
        self.my_metric_key = "cpustats"
        self.observer.calculated_results[self.my_metric_key] = dict()

    def get_cpustats(self, index):
        cpu_stats = dict()
        cpu_last = self.cpu_io_counters(index)
        cpu_curr = self.cpu_io_counters(index + 1)

        for device in cpu_curr.keys():
            calculations = {
                k: round(v, 2) for k, v in self.cpustats_calc(
                    last=cpu_last[device],
                    curr=cpu_curr[device]
                ).items()
            }
            cpu_stats[device] = calculations

        self.observer.calculated_results[self.my_metric_key][index] = cpu_stats

    @staticmethod
    def cpustats_calc(last, curr):
        cpu_stats = {}

        deltas = {stat: int(curr[stat]) - int(last[stat]) for stat in curr.keys() if stat is not "dev"}
        sum_deltas = sum([deltas[stat_delta] for stat_delta in deltas.keys()])

        def calc_deltas(field):
            return float(deltas[field]) / sum_deltas * 100

        cpu_stats['%usr'] = calc_deltas('user')
        cpu_stats['%nice'] = calc_deltas('nice')
        cpu_stats['%sys'] = calc_deltas('system')
        cpu_stats['%iowait'] = calc_deltas('iowait')
        cpu_stats['%irq'] = calc_deltas('irq')
        cpu_stats['%soft'] = calc_deltas('softirq')
        cpu_stats['%steal'] = calc_deltas('steal')
        cpu_stats['%guest'] = calc_deltas('guest')
        cpu_stats['%gnice'] = calc_deltas('guest_nice')
        cpu_stats['%idle'] = calc_deltas('idle')

        return cpu_stats

    @staticmethod
    def parse_cpustats(line):
        dev, user, nice, system, idle, iowait, irq, softirq, steal, guest, guest_nice = line.split()
        del line
        d = {k: v for k, v in locals().items()}
        return d

    def cpu_io_counters(self, index):
        read_cpu_stats = self.observer.file_content[index]['/proc/stat'][:os.cpu_count()+1]
        cpu_stats = [self.parse_cpustats(line) for line in read_cpu_stats]
        cpu_stats = {stat['dev']: stat for stat in cpu_stats}
        return cpu_stats

    def get_deltams(self, index):
        cpu_last = self.cpu_io_counters(index)['cpu']
        cpu_curr = self.cpu_io_counters(index + 1)['cpu']

        curr_cpu_load = int(cpu_curr['user']) + int(cpu_curr['system']) + \
            int(cpu_curr['idle']) + int(cpu_curr['iowait'])

        last_cpu_load = int(cpu_last['user']) + int(cpu_last['system']) + \
            int(cpu_last['idle']) + int(cpu_last['iowait'])

        hz = os.sysconf(os.sysconf_names['SC_CLK_TCK'])
        deltams = 1000 * (int(curr_cpu_load) - int(last_cpu_load)) / os.cpu_count() / hz
        return deltams


class VMStats:
    def __init__(self, observer):
        self.observer = observer
        self.my_metric_key = "vmstats"
        self.observer.calculated_results[self.my_metric_key] = dict()

    def get_vmstats(self, index):
        vmstats = self.vmstat_counters(index)
        self.observer.calculated_results[self.my_metric_key][index] = vmstats

    @staticmethod
    def parse_loadavg(line):
        one_min, five_min, fifteen_min, curr_proc, last_proc_id = line.split()
        proc_scheduled = curr_proc.split('/')[0]
        entities_total = curr_proc.split('/')[1]
        del line, curr_proc
        d = {k: v for k, v in locals().items()}
        return d

    def vmstat_counters(self, index):
        read_loadvg = self.observer.file_content[index]['/proc/loadavg'][0]
        read_vmstat = self.observer.file_content[index]['/proc/vmstat']

        vmstats = dict()
        vmstats['loadavg'] = self.parse_loadavg(read_loadvg)
        vmstats['vmstat'] = {stat.split()[0]: int(stat.split()[1]) for stat in read_vmstat}
        return vmstats


class DiskStats:
    def __init__(self, observer):
        print("NEW INSTANCE")
        self.sector_size = 512
        self.observer = observer
        self.my_metric_key = 'diskstats'
        self.observer.calculated_results[self.my_metric_key] = dict()

    def analyze_diskstats(self):
        my_alert_data = self.observer.alert_data[self.my_metric_key]

        for alert_metric, alert_value in my_alert_data.items():
            warning_value = int(alert_value['warning'])
            critical_value = int(alert_value['critical'])

            for device, device_stats in self.observer.average_values[self.my_metric_key].items():
                actual_value = int(device_stats[alert_metric])
                self.observer.compare_values(
                    metrics=locals()
                )

    def generate_totals(self, index):
        diskstat_results = self.observer.calculated_results[self.my_metric_key][index]

        for device, device_stats in diskstat_results.items():
            if device not in self.observer.average_values[self.my_metric_key].keys():
                self.observer.average_values[self.my_metric_key][device] = device_stats
                self.observer.min_values[self.my_metric_key][device] = device_stats.copy()
                self.observer.max_values[self.my_metric_key][device] = device_stats.copy()
            else:
                for stat, stat_value in device_stats.items():
                    self.observer.average_values[self.my_metric_key][device][stat] = \
                        self.observer.average_values[self.my_metric_key][device][stat] + float(stat_value)

                    if float(self.observer.min_values[self.my_metric_key][device][stat]) > float(stat_value):
                        self.observer.min_values[self.my_metric_key][device][stat] = float(stat_value)

                    if float(self.observer.max_values[self.my_metric_key][device][stat]) < float(stat_value):
                        self.observer.max_values[self.my_metric_key][device][stat] = float(stat_value)

    def generate_averages(self):
        for device in self.observer.average_values[self.my_metric_key]:
            for stat, stat_value in self.observer.average_values[self.my_metric_key][device].items():
                self.observer.average_values[self.my_metric_key][device][stat] = \
                    float(self.observer.average_values[self.my_metric_key][device][stat]) / (self.observer.count - 1)

    def get_diskstats(self, index, deltams):
        disk_stats = dict()
        disk_last = self.disk_io_counters(index)
        disk_curr = self.disk_io_counters(index + 1)

        for device in disk_curr.keys():
            calculations = {
                k: round(v, 2) for k, v in self.calc(
                    last=disk_last[device],
                    curr=disk_curr[device],
                    ts_delta=self.observer.get_ts_delta(index),
                    deltams=deltams
                ).items()
            }
            disk_stats[device] = calculations

        self.observer.calculated_results[self.my_metric_key][index] = disk_stats

    def calc(self, last, curr, ts_delta, deltams):
        disk_stats = {}

        def delta(field):
            return (int(curr[field]) - int(last[field])) / ts_delta

        disk_stats['rrqm/s'] = delta('r_merges')
        disk_stats['wrqm/s'] = delta('w_merges')
        disk_stats['r/s'] = delta('r_ios')
        disk_stats['w/s'] = delta('w_ios')
        disk_stats['iops'] = int(disk_stats['r/s']) + int(disk_stats['w/s'])
        disk_stats['rkB/s'] = delta('r_sec') * self.sector_size / 1024
        disk_stats['wkB/s'] = delta('w_sec') * self.sector_size / 1024
        disk_stats['avgrq-sz'] = 0
        disk_stats['avgqu-sz'] = delta('rq_ticks') / 1000

        if disk_stats['r/s'] + disk_stats['w/s'] > 0:
            disk_stats['avgrq-sz'] = (delta('r_sec') + delta('w_sec')) / (delta('r_ios') + delta('w_ios'))
            disk_stats['await'] = (delta('r_ticks') + delta('w_ticks')) / (delta('r_ios') + delta('w_ios'))
            disk_stats['r_await'] = delta('r_ticks') / delta('r_ios') if delta('r_ios') > 0 else 0
            disk_stats['w_await'] = delta('w_ticks') / delta('w_ios') if delta('w_ios') > 0 else 0
            disk_stats['svctm'] = delta('tot_ticks') / (delta('r_ios') + delta('w_ios'))
        else:
            disk_stats['avgrq-sz'] = 0
            disk_stats['await'] = 0
            disk_stats['r_await'] = 0
            disk_stats['w_await'] = 0
            disk_stats['svctm'] = 0

        blkio_ticks = int(curr["tot_ticks"]) - int(last["tot_ticks"])
        util = (100 * blkio_ticks / deltams) if (100 * blkio_ticks / deltams) < 100 else 100
        disk_stats['%util'] = util

        return disk_stats

    def disk_io_counters(self, index):
        read_partitions = self.observer.file_content[index]['/proc/partitions'][2:]
        partitions = set([part.split()[-1] for part in read_partitions if not isinstance(part.strip()[-1], int)])

        read_diskstats = self.observer.file_content[index]['/proc/diskstats']
        disk_stats = [self.parse_diskstats(line) for line in read_diskstats]
        disk_stats = {stat['dev']: stat for stat in disk_stats if stat['dev'] in partitions}

        return disk_stats

    @staticmethod
    def parse_diskstats(line):
        major, minor, dev, r_ios, r_merges, r_sec, r_ticks, w_ios, w_merges, \
            w_sec, w_ticks, ios_pgr, tot_ticks, rq_ticks = line.split()

        del line
        d = {k: v for k, v in locals().items()}
        return d


class NetStats:
    def __init__(self, observer):
        self.observer = observer
        self.my_metric_key = "netstats"
        self.observer.calculated_results[self.my_metric_key] = dict()

    def get_netstats(self, index):
        netstats = dict()
        netstats = {"eth0": {"metric", "metric_value"}}
        self.observer.calculated_results[self.my_metric_key][index] = netstats


class Observer:
    def __init__(self, sleep, count, path_to_json="conf/alerts.json"):
        self.sleep = sleep
        self.count = count
        self.file_content = dict()
        self.calculated_results = dict()
        self.proc_file_dictionary = {
            "/proc/diskstats": "/proc/diskstats",
            "/proc/partitions": "/proc/partitions",
            "/proc/stat": "/proc/stat",
            "/proc/loadavg": "/proc/loadavg",
            "/proc/vmstat": "/proc/vmstat"
        }
        self.file_content = self.load_file_data(sleep, count)
        self.path_to_json = path_to_json
        self.alert_data = self.json_reader()
        self.system_uptime_seconds = self.get_system_uptime()
        self.average_values = dict()
        self.max_values = dict()
        self.min_values = dict()

        self.diskstats = DiskStats(self)
        self.average_values[self.diskstats.my_metric_key] = dict()
        self.max_values[self.diskstats.my_metric_key] = dict()
        self.min_values[self.diskstats.my_metric_key] = dict()


        self.vmstats = VMStats(self)
        #self.average_values[self.vmstats.my_metric_key] = dict()

        self.procceses = Processes(self)
        #self.average_values[self.procceses.my_metric_key] = dict()

        self.netstats = NetStats(self)
        #self.average_values[self.netstats.my_metric_key] = dict()

        self.cpustats = CPUStats(self)
        #self.average_values[self.cpustats.my_metric_key] = dict()

    def generate_calculations(self):
        for index in range(1, self.count):
            self.diskstats.get_diskstats(index, self.cpustats.get_deltams(index)),
            self.cpustats.get_cpustats(index),
            self.vmstats.get_vmstats(index),
            self.netstats.get_netstats(index)

        #self.display_calculations()
        self.run_analyzer()

    def display_calculations(self):
        for stat in self.calculated_results.keys():
            for index in self.calculated_results[stat].keys():
                rounded_ts_delta = round(int(self.get_ts_delta(index)), 4)
                last_ts = self.file_content[index]['ts']
                curr_ts = self.file_content[index + 1]['ts']
                print("Generation completed - displaying results...")
                print("")
                start_date = time.strftime("%Z - %Y/%m/%d, %H:%M:%S", time.localtime(last_ts))
                end_date = time.strftime("%Z - %Y/%m/%d, %H:%M:%S", time.localtime(curr_ts))
                print("[%s-%s] Statistics from [%s] to [%s] (Delta: %s ms)" % (
                    stat, index, start_date, end_date, rounded_ts_delta
                ))
                print("----------------------------------------------------------------------------------------------")
                for stat_name, stat_values in self.calculated_results[stat][index].items():
                    print(stat_name, stat_values)
                print("")

    def run_analyzer(self):
        for index in range(1, self.count):
            self.diskstats.generate_totals(index)

        self.diskstats.generate_averages()

        for stat, values in self.average_values.items():
            print(stat)
            for device in values:
                print(device, {k: {
                    "Min": self.min_values[stat][device][k],
                    "Average": round(v, 2),
                    "Max": self.max_values[stat][device][k]
                } for k, v in values[device].items()})

    def load_file_data(self, sleep, count):
        assert count >= 2, 'Count must be equal or greater 2'

        print("Will generate [%s] metrics with [%s] seconds time interval" % (count, sleep))
        for index in range(1, count):
            self.file_content[index] = dict()
            self.file_reader(index)
            time.sleep(sleep)

        self.file_content[count] = dict()
        self.file_reader(count)

        return self.file_content

    def file_reader(self, index):
        print("Generating metrics with index [%s]" % index)
        for proc, file_name in self.proc_file_dictionary.items():
            with open(file_name) as f:
                self.file_content[index][proc] = f.readlines()
                self.file_content[index]['ts'] = os.stat(f.name).st_mtime

    def get_ts_delta(self, index):
        return self.file_content[index+1]["ts"] - self.file_content[index]["ts"]

    def json_reader(self):
        return json.loads(open(self.path_to_json).read())

    def compare_values(self, metrics):
        if metrics['actual_value'] >= metrics['critical_value']:
            print("Device [%s]: [%s] has reached critical value [%s]" % (
                metrics['device'], metrics['alert_metric'], metrics['actual_value']
            ))
            status = "CRITICAL"
            #self.end_results["CRITICAL"][]
        elif metrics['actual_value'] >= metrics['warning_value']:
            print("Device [%s]: [%s] has reached warning value [%s]" % (
                metrics['device'], metrics['alert_metric'], metrics['actual_value']
            ))
            status = "WARNING"
        else:
            status = "OK"

        return status

    def calculate_averages(self):
        pass

    @staticmethod
    def get_system_uptime():
        with open('/proc/uptime', 'r') as f:
            uptime_seconds = float(f.readline().split()[0])

        return uptime_seconds

if __name__ == '__main__':
    start = time.time()
    _sleep = 1
    _count = 2
    o = Observer(sleep=_sleep, count=_count)
    o.generate_calculations()
    print("Finished calculations in [%s] seconds" % (time.time() - start - (_count - 1)))
